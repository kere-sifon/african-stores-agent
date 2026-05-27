# pipeline.py
# ─────────────────────────────────────────────────────────────────────────────
# A deterministic pipeline that replaces the ReAct agent loop for the core
# search → scrape → extract → save sequence.
#
# WHY: Small local models (3B/7B) make bad judgment calls in long ReAct loops.
# They skip valid stores, scrape irrelevant pages, and forget to save.
#
# LESSON: Use agents for genuinely open-ended tasks. Use direct pipelines
# when the sequence of steps is predictable. Both use LangChain — the
# extractor chain (prompt | llm | parser) still does all the LLM work.
#
# This pipeline:
#   1. Calls search_for_stores directly (no agent decision needed)
#   2. Parses URLs from results
#   3. Scrapes each URL (skips 4xx errors automatically)
#   4. Sends scraped text to the LangChain extraction CHAIN in extractor.py
#   5. Saves valid results to the configured database (SQLite or MongoDB)
# ─────────────────────────────────────────────────────────────────────────────

import re
import time
from typing import Optional
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from langchain_community.tools import DuckDuckGoSearchResults

from config import (
    CRAWL_DELAY_SECONDS,
    DIASPORA_LISTINGS_PER_RUN,
    DIRECTORY_SITES,
    DIRECTORY_SITES_PER_RUN,
    MAPS_SEARCH_ENABLED,
    MAPS_SEARCH_RESULTS,
    MAX_RESULTS_PER_QUERY,
    SEARCH_QUERIES,
    STORE_CONTACT_RULE,
    TARGET_CITIES,
    YELP_LISTINGS_PER_RUN,
)
from extractor import extract_store_info
from models import StoreInfo
from storage import get_stats, init_db, save_store, store_exists

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

# Domains that reliably block scrapers — skip immediately
BLOCKED_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "linkedin.com",
    "reddit.com",
    "narcity.com",
    "blogto.com",
    "bestbuy.ca",
    "canada.ca",
    "amazon.ca",
    "play.google.com",
    "support.google.com",
    "developers.google.com",
    "mapsplatform.google.com",
    "thatlocalgirl.com",
    "ileoja.ca",  # listicles / directory articles, not individual stores
    "cbc.ca",
    "nih.gov",
    "ncbi.nlm.nih.gov",
]

# Cities accepted when crawling a given TARGET_CITIES entry (GTA for Toronto, etc.)
CITY_SEARCH_ALIASES: dict[str, frozenset[str]] = {
    "toronto, ontario": frozenset(
        {
            "toronto",
            "scarborough",
            "north york",
            "etobicoke",
            "mississauga",
            "brampton",
            "markham",
            "thornhill",
            "vaughan",
            "richmond hill",
            "ajax",
            "pickering",
            "oakville",
            "hamilton",
        }
    ),
    "montreal, quebec": frozenset(
        {
            "montreal",
            "laval",
            "longueuil",
            "brossard",
            "terrebonne",
        }
    ),
    "calgary, alberta": frozenset({"calgary", "airdrie"}),
    "vancouver, british columbia": frozenset(
        {
            "vancouver",
            "burnaby",
            "surrey",
            "richmond",
            "new westminster",
        }
    ),
    "ottawa, ontario": frozenset({"ottawa", "gatineau", "kanata", "nepean"}),
}

# Major chains — never directory entries for African store searches
EXCLUDED_MAJOR_CHAINS = (
    "loblaws",
    "loblaw",
    "walmart",
    "sobeys",
    "nofrills",
    "no frills",
    "costco",
    "real canadian superstore",
    "food basics",
    "freshco",
    "longo's",
    "farm boy",
    "whole foods",
    "shoppers drug",
    "giant tiger",
)

# Directory platform names mistaken for store names by the extractor
INVALID_BUSINESS_NAMES = (
    "diasporastores",
    "diasporastores.ca",
    "diaspora stores",
    "yelp",
    "yelp.ca",
)

AFRICAN_SIGNALS = (
    "african",
    "nigerian",
    "ghana",
    "ghanaian",
    "ethiopian",
    "somali",
    "kenyan",
    "congolese",
    "cameroon",
    "senegal",
    "west african",
    "east african",
    "caribbean",
    "jollof",
    "egusi",
    "plantain",
    "injera",
    "fufu",
    "suya",
    "mychopchop",
    "chopchop",
)

# region_focus values that indicate a real African grocery (not generic SEO)
SPECIFIC_AFRICAN_REGIONS = (
    "west african",
    "east african",
    "south african",
    "central african",
    "nigerian",
    "ghanaian",
    "ethiopian",
    "somali",
    "senegalese",
    "kenyan",
    "congolese",
    "cameroonian",
    "caribbean",
)

STRONG_AFRICAN_DESC_PHRASES = (
    "african groc",
    "african food",
    "african market",
    "african restaurant",
    "african essentials",
    "authentic african",
    "west african",
    "east african",
    "south african",
    "nigerian",
    "ghanaian",
    "ethiopian",
    "caribbean grocery",
)

# ── Step 1: Search ─────────────────────────────────────────────────────────────


def search(query: str, num_results: int = 8) -> list[dict]:
    """Call DuckDuckGo and return list of {title, url, snippet}."""
    try:
        time.sleep(CRAWL_DELAY_SECONDS)
        ddg = DuckDuckGoSearchResults(num_results=num_results, output_format="list")
        results = ddg.invoke(query)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
            }
            for r in results
            if r.get("link")
        ]
    except Exception as e:
        print(f"  [search] Error: {e}")
        return []


def is_google_maps_place(url: str) -> bool:
    """True for Google Maps business listings with a place name in the URL path."""
    return parse_maps_place_name(url) is not None


def is_yelp_biz_page(url: str) -> bool:
    lower = url.lower()
    return "yelp." in lower and "/biz/" in lower


def is_yelp_search_or_list_page(url: str, title: str = "") -> bool:
    """Yelp search results, listicles, and non-Canada SERP noise."""
    lower = url.lower()
    if "yelp." not in lower:
        return False
    if is_yelp_biz_page(url):
        return False
    if "/search" in lower or "find_desc=" in lower or "find_loc=" in lower:
        return True
    title_lower = title.lower()
    if title_lower.startswith("top 10 best") or title_lower.startswith("top 10 "):
        return True
    return True


def is_diaspora_store_listing(url: str) -> bool:
    """Single-store page on diasporastores.ca (not blog/listicle)."""
    lower = url.lower()
    return "diasporastores.ca" in lower and "/stores/listing/" in lower


def search_for_city(category: str, city: str) -> list[dict]:
    """
    Directory site: searches first, then general web. Blocked URLs are removed
    before the scrape loop so attempt slots are not wasted on junk.
    """
    city_name = city.split(",")[0].strip()
    province = city.split(",")[1].strip() if "," in city else ""

    merged: dict[str, dict] = {}

    for site in DIRECTORY_SITES[:DIRECTORY_SITES_PER_RUN]:
        if "yelp" in site:
            directory_query = f"{category} {city_name} site:yelp.ca inurl:biz".strip()
        else:
            directory_query = f"{category} {city_name} {site}".strip()
        print(f"  📒 Directory search: {directory_query}")
        for row in search(directory_query, num_results=5):
            merged.setdefault(row["url"], row)

    if MAPS_SEARCH_ENABLED:
        maps_query = f"{category} {city_name} {province} site:google.com/maps".strip()
        print(f"  🗺️  Maps search (legacy): {maps_query}")
        for row in search(maps_query, num_results=MAPS_SEARCH_RESULTS):
            merged.setdefault(row["url"], row)

    general_query = f'"{category}" {city_name} {province} Canada'.strip()
    print(f"  🔍 Web search: {general_query}")
    for row in search(general_query, num_results=8):
        merged.setdefault(row["url"], row)

    results = [
        r
        for r in merged.values()
        if not is_blocked_url(r["url"])
        and not is_yelp_search_or_list_page(r["url"], r.get("title", ""))
    ]
    results = [
        r
        for r in results
        if not ("/maps/place/" in r["url"].lower() and not is_google_maps_place(r["url"]))
    ]
    results.sort(key=_result_sort_key)
    results = _balance_result_queue(results)
    print(f"  Found {len(results)} scrapeable URLs (queued for extraction)")
    return results


def _balance_result_queue(results: list[dict]) -> list[dict]:
    """Cap Yelp and diaspora listings so other sources get attempt slots."""
    yelp_rows: list[dict] = []
    diaspora_rows: list[dict] = []
    other_rows: list[dict] = []

    for row in results:
        url = row.get("url", "")
        if is_yelp_biz_page(url):
            yelp_rows.append(row)
        elif is_diaspora_store_listing(url):
            diaspora_rows.append(row)
        else:
            other_rows.append(row)

    return (
        yelp_rows[:YELP_LISTINGS_PER_RUN] + diaspora_rows[:DIASPORA_LISTINGS_PER_RUN] + other_rows
    )


def _directory_domain_in_url(url: str) -> bool:
    lower = url.lower()
    return any(site.replace("site:", "") in lower for site in DIRECTORY_SITES)


def _result_sort_key(row: dict) -> tuple[int, int]:
    """Scrapeable store listings first, then Yelp (metadata-only), then general."""
    url = row.get("url", "")
    title = row.get("title", "")
    lower = url.lower()
    if is_yelp_biz_page(url):
        return (0, 0)
    if is_diaspora_store_listing(url):
        return (0, 1)
    if is_google_maps_place(url):
        return (0, 2)
    if _directory_domain_in_url(url):
        return (0, 3)
    score = 1
    if "african" in lower or "african" in title.lower():
        score = 0
    if any(p in lower for p in ("/blog/", "/thread/", "/documentation", "/collections/")):
        score += 1
    return (1, score)


# ── Step 2: Filter URLs ────────────────────────────────────────────────────────


def is_blocked_url(url: str) -> bool:
    """Block junk domains; allow Yelp /biz/, Maps /place/, diaspora store listings."""
    lower = url.lower()
    if is_google_maps_place(url):
        return False
    if is_yelp_biz_page(url):
        return False
    if "yelp." in lower:
        return True
    if is_diaspora_store_listing(url):
        return False
    if "diasporastores.ca" in lower:
        return True
    if "google.com" in lower or "google.ca" in lower or "maps.google." in lower:
        return True
    return any(domain in lower for domain in BLOCKED_DOMAINS)


def is_scrapeable(url: str) -> bool:
    return not is_blocked_url(url)


# ── Step 3: Scrape ─────────────────────────────────────────────────────────────


def scrape(url: str, max_chars: int = 4000) -> Optional[str]:
    """
    Fetch and clean a page. Returns plain text or None on failure.
    Never raises — all errors return None so the pipeline continues.
    """
    try:
        time.sleep(CRAWL_DELAY_SECONDS)
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except requests.exceptions.HTTPError as e:
        print(f"  [scrape] HTTP {e.response.status_code} — skipping {url}")
        return None
    except Exception as e:
        print(f"  [scrape] Error on {url}: {e}")
        return None


# ── Step 4 + 5: Extract and save ───────────────────────────────────────────────


def _is_store_website(url: str) -> bool:
    if not url or not url.strip():
        return False
    if is_google_maps_place(url) or is_yelp_biz_page(url) or is_diaspora_store_listing(url):
        return False
    return not is_blocked_url(url)


def _is_excluded_chain(name_lower: str) -> bool:
    for chain in EXCLUDED_MAJOR_CHAINS:
        if re.search(rf"\b{re.escape(chain)}\b", name_lower):
            return True
    return False


def _is_invalid_business_name(name: str) -> bool:
    lower = name.strip().lower()
    if len(lower) < 3:
        return True
    return any(invalid in lower for invalid in INVALID_BUSINESS_NAMES)


def parse_listing_slug_hint(url: str) -> Optional[str]:
    """Business name hint from diasporastores /stores/listing/slug/."""
    match = re.search(r"/stores/listing/([^/?]+)", url, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).replace("-", " ").strip()


def infer_city_from_listing_slug(url: str, aliases: frozenset[str]) -> Optional[str]:
    """City token embedded in listing URL slug (e.g. ...-grocery-toronto)."""
    lower = url.lower()
    for alias in sorted(aliases, key=len, reverse=True):
        token = alias.replace(" ", "-")
        if re.search(rf"-{re.escape(token)}(?:-|$)", lower):
            return alias.title()
    return None


def enrich_diaspora_listing_text(url: str, text: str) -> str:
    slug_hint = parse_listing_slug_hint(url)
    if not slug_hint:
        return text
    return (
        f"This page is ONE business listing on diasporastores.ca. "
        f"Business slug: {slug_hint}. "
        f"Extract that business only — not the diasporastores platform.\n\n{text}"
    )


def parse_maps_place_name(url: str) -> Optional[str]:
    """Business name from /maps/place/Name+Here/... path segment."""
    match = re.search(r"/maps/place/([^/@?]+)", url)
    if not match:
        return None
    name = unquote(match.group(1).replace("+", " "))
    return name.strip() if name else None


def build_maps_extraction_text(title: str, snippet: str, url: str, city_hint: str) -> str:
    """Build text for the extractor from Maps search metadata (page scrape usually fails)."""
    place_name = parse_maps_place_name(url)
    parts = [
        "Source: Google Maps business listing.",
        f"Search area: {city_hint}.",
        f"Listing title: {title}.",
        f"Maps snippet: {snippet}.",
    ]
    if place_name:
        parts.append(f"Place name from URL: {place_name}.")
    parts.append(
        "Extract the store's street address, phone, and hours from the snippet when present."
    )
    return " ".join(parts)


def process_maps_place(title: str, snippet: str, url: str, city_hint: str) -> bool:
    """Extract store info from Maps listing metadata without scraping the Maps page."""
    print("  [maps] Using Google Maps listing (snippet + place URL)")
    text = build_maps_extraction_text(title, snippet, url, city_hint)
    return extract_and_save(text, city_hint, url)


def parse_yelp_slug_name(url: str) -> Optional[str]:
    """Business name hint from /biz/slug-city segment."""
    match = re.search(r"/biz/([^/?]+)", url, re.IGNORECASE)
    if not match:
        return None
    slug = match.group(1)
    # Drop trailing city tokens (e.g. grocery-africa-toronto-2)
    name = re.sub(
        r"-(?:toronto|mississauga|scarborough|vaughan|markham|brampton|ottawa|"
        r"montreal|calgary|vancouver|canada)(?:-\d+)?$",
        "",
        slug,
        flags=re.IGNORECASE,
    )
    return name.replace("-", " ").strip() or slug.replace("-", " ").strip()


def build_yelp_extraction_text(title: str, snippet: str, url: str, city_hint: str) -> str:
    """Yelp blocks scrapers — use search title/snippet (often includes address)."""
    slug_name = parse_yelp_slug_name(url)
    parts = [
        "Source: Yelp business listing (search result metadata; page not scraped).",
        f"Search area: {city_hint}.",
        f"Listing title: {title}.",
        f"Yelp snippet: {snippet}.",
        f"Yelp URL: {url}.",
    ]
    if slug_name:
        parts.append(f"Business name from URL slug: {slug_name}.")
    parts.append(
        "The listing title often contains street address and city before '- Yelp'. "
        "Extract name, address, city, phone, hours, and category from title and snippet."
    )
    return " ".join(parts)


def process_yelp_listing(title: str, snippet: str, url: str, city_hint: str) -> bool:
    """Extract store info from Yelp search metadata (Yelp returns HTTP 403 to scrapers)."""
    print("  [yelp] Using Yelp listing metadata (snippet + title; no scrape)")
    text = build_yelp_extraction_text(title, snippet, url, city_hint)
    return extract_and_save(text, city_hint, url)


def infer_city_from_address(address: str, aliases: frozenset[str]) -> Optional[str]:
    """Match a GTA (or search-area) city name embedded in a street address."""
    addr = address.lower()
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", addr):
            return alias.title()
    return None


def apply_address_city(store: StoreInfo, city_hint: str, source_url: str = "") -> None:
    """Prefer city from listing URL slug, then street address, over marketing copy."""
    key = city_hint.strip().lower()
    aliases = CITY_SEARCH_ALIASES.get(key)
    if not aliases:
        return
    if source_url:
        slug_city = infer_city_from_listing_slug(source_url, aliases)
        if slug_city:
            store.city = slug_city
    if not store.address:
        return
    inferred = infer_city_from_address(store.address, aliases)
    if inferred:
        store.city = inferred


def align_city_with_search(store: StoreInfo, city_hint: str, source_url: str = "") -> bool:
    """
    Keep listings tied to the city being crawled.
    Online retailers based elsewhere may use the search city if they serve that area.
    """
    key = city_hint.strip().lower()
    aliases = CITY_SEARCH_ALIASES.get(key)
    hint_city = city_hint.split(",")[0].strip()
    hint_lower = hint_city.lower()

    apply_address_city(store, city_hint, source_url)

    if not aliases:
        return True

    store_city = (store.city or "").strip().lower()
    has_address = bool(store.address and store.address.strip())
    desc = (store.description or "").lower()

    if not store_city:
        store.city = hint_city
        return True

    if store_city in aliases:
        return True

    # Nationwide online grocer — no physical address in the search metro
    if not has_address and (store.website or store.source_url):
        if any(term in desc for term in ("online", "canada", "delivery", "ship", "nationwide")):
            store.city = hint_city
            print(f"  [save] Online retailer listed under {hint_city}")
            return True

    if hint_lower in desc and (store.website or store.source_url):
        store.city = hint_city
        print(f"  [save] Listed under {hint_city} (serves area, based in {store_city.title()})")
        return True

    print(
        f"  [save] City '{store.city}' outside {hint_city} area — skipped "
        f"(physical address may be elsewhere)"
    )
    return False


def is_relevant_african_store(store: StoreInfo) -> bool:
    """
    Filter out major chains and pages with no African focus.
    African keywords in description alone (SEO) are not enough — require
    name, a specific region, or product signals.
    """
    name_lower = (store.name or "").lower()
    if _is_excluded_chain(name_lower):
        return False

    if any(signal in name_lower for signal in AFRICAN_SIGNALS):
        return True

    region = (store.region_focus or "").lower()
    if any(r in region for r in SPECIFIC_AFRICAN_REGIONS):
        return True

    if store.products_and_specialties:
        prods = " ".join(store.products_and_specialties).lower()
        if any(signal in prods for signal in AFRICAN_SIGNALS):
            return True

    desc = (store.description or "").lower()
    if any(phrase in desc for phrase in STRONG_AFRICAN_DESC_PHRASES):
        return True

    return False


def store_meets_quality(store: StoreInfo, source_url: str = "") -> bool:
    """Return False if the record lacks enough contact info for a public directory."""
    has_address = bool(store.address and store.address.strip())
    has_phone = bool(store.phone and store.phone.strip())
    website = (store.website or "").strip() or (
        source_url.strip() if _is_store_website(source_url) else ""
    )
    has_website = bool(website)

    if STORE_CONTACT_RULE == "address":
        return has_address
    # default "contact": at least one verifiable way to find the business
    return has_address or has_phone or has_website


def extract_and_save(text: str, city_hint: str, source_url: str) -> bool:
    """
    Send scraped text to the LangChain extraction chain, then save to DB.
    Returns True if a store was successfully saved.
    """
    store = extract_store_info(text, city_hint)  # LangChain LCEL chain
    if not store:
        print(f"  [extract] No store data extracted from {source_url}")
        return False

    apply_address_city(store, city_hint, source_url)

    if not store.name or _is_invalid_business_name(store.name):
        print("  [extract] Invalid or platform business name — skipping")
        return False

    store.source_url = source_url
    if not store.city:
        store.city = city_hint.split(",")[0].strip()

    if _is_store_website(source_url) and not store.website:
        store.website = source_url

    if not align_city_with_search(store, city_hint, source_url):
        return False

    if store_exists(store.name, store.city):
        print(f"  [save] Already exists: {store.name} ({store.city}) — skipped")
        return False

    if not is_relevant_african_store(store):
        print(f"  [save] Not African-focused or excluded chain — skipped ({store.name})")
        return False

    if not store_meets_quality(store, source_url):
        print(
            f"  [save] No address/phone/website — skipped (STORE_CONTACT_RULE={STORE_CONTACT_RULE})"
        )
        return False

    success, message = save_store(store)
    print(f"  [save] {message}")
    return success


def save_from_snippet(snippet: str, title: str, city_hint: str, url: str) -> bool:
    """
    Last resort: extract and save using only the search snippet + title.
    Used when ALL scrape attempts for a result fail.
    """
    text = f"{title}. {snippet}. Located in {city_hint}."
    return extract_and_save(text, city_hint, url)


# ── Main pipeline ──────────────────────────────────────────────────────────────


def run_pipeline_for_city(city: str, category: str) -> int:
    """
    Full pipeline for one city + category combination.
    Returns the number of stores saved.
    """
    print(f"\n  Searching in: {city}")
    results = search_for_city(category, city)

    if not results:
        print("  No search results returned.")
        return 0

    saved = 0
    attempted = 0

    for result in results:
        url = result["url"]
        title = result["title"]
        snippet = result["snippet"]

        print(f"\n  → {title[:60]}")
        print(f"    {url[:80]}")

        if is_blocked_url(url) or is_yelp_search_or_list_page(url, title):
            print("  [skip] Blocked or non-business URL")
            continue

        if attempted >= MAX_RESULTS_PER_QUERY:
            print(f"  [skip] Reached max scrape attempts ({MAX_RESULTS_PER_QUERY})")
            break

        if is_google_maps_place(url):
            attempted += 1
            if process_maps_place(title, snippet, url, city):
                saved += 1
            continue

        if is_yelp_biz_page(url):
            attempted += 1
            if process_yelp_listing(title, snippet, url, city):
                saved += 1
            continue

        attempted += 1
        text = scrape(url)
        if not text:
            print("  [skip] Scrape failed — no page content")
            continue
        if is_diaspora_store_listing(url):
            text = enrich_diaspora_listing_text(url, text)
        if extract_and_save(text, city, url):
            saved += 1
        else:
            print("  [skip] Extracted but not saved (filters or duplicate)")

    return saved


def run_test_pipeline(city: str = "Toronto, Ontario", category: str = "African grocery store"):
    """Single city/category test run."""
    from storage import storage_summary

    init_db()
    print(f"\n🧪 Pipeline test: {category} in {city}")
    print(f"   {storage_summary()}\n")
    saved = run_pipeline_for_city(city, category)
    print(f"\n✅ Done. Saved {saved} store(s) this run.")
    stats = get_stats()
    print(f"   Total in database: {stats['total']}")


def run_full_pipeline():
    """Full crawl across all cities and categories."""
    init_db()
    total_saved = 0
    total_tasks = len(TARGET_CITIES) * len(SEARCH_QUERIES)
    completed = 0

    for city in TARGET_CITIES:
        for query in SEARCH_QUERIES:
            completed += 1
            print(f"\n{'=' * 60}")
            print(f"[{completed}/{total_tasks}] {query} in {city}")
            print(f"{'=' * 60}")
            try:
                saved = run_pipeline_for_city(city, query)
                total_saved += saved
            except Exception as e:
                print(f"  [pipeline] Error: {e} — continuing...")

    print(f"\n✅ Full crawl complete. Total saved this run: {total_saved}")
    stats = get_stats()
    print(f"   Total in database: {stats['total']}")
    for row in stats["by_city"]:
        print(f"   {row['city']}: {row['count']} stores")
