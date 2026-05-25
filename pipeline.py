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
#   5. Saves valid results to SQLite
# ─────────────────────────────────────────────────────────────────────────────

import re
import time
from typing import Optional
from urllib.parse import unquote

from langchain_community.tools import DuckDuckGoSearchResults

from extractor import extract_store_info
from storage import init_db, save_store, store_exists, get_stats
from config import (
    TARGET_CITIES,
    SEARCH_QUERIES,
    MAX_RESULTS_PER_QUERY,
    CRAWL_DELAY_SECONDS,
    STORE_CONTACT_RULE,
    MAPS_SEARCH_ENABLED,
    MAPS_SEARCH_RESULTS,
)
from models import StoreInfo

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

# Domains that reliably block scrapers — skip immediately
BLOCKED_DOMAINS = [
    "facebook.com", "instagram.com", "tiktok.com", "youtube.com", "youtu.be",
    "yelp.com", "twitter.com", "linkedin.com", "reddit.com",
    "narcity.com", "blogto.com", "bestbuy.ca", "canada.ca", "amazon.ca",
    "play.google.com", "support.google.com", "developers.google.com",
    "mapsplatform.google.com",
    "thatlocalgirl.com",
    "ileoja.ca",  # listicles / directory articles, not individual stores
]

# Cities accepted when crawling a given TARGET_CITIES entry (GTA for Toronto, etc.)
CITY_SEARCH_ALIASES: dict[str, frozenset[str]] = {
    "toronto, ontario": frozenset({
        "toronto", "scarborough", "north york", "etobicoke", "mississauga",
        "brampton", "markham", "thornhill", "vaughan", "richmond hill",
        "ajax", "pickering", "oakville", "hamilton",
    }),
    "montreal, quebec": frozenset({
        "montreal", "laval", "longueuil", "brossard", "terrebonne",
    }),
    "calgary, alberta": frozenset({"calgary", "airdrie"}),
    "vancouver, british columbia": frozenset({
        "vancouver", "burnaby", "surrey", "richmond", "new westminster",
    }),
    "ottawa, ontario": frozenset({"ottawa", "gatineau", "kanata", "nepean"}),
}

# Major chains — never directory entries for African store searches
EXCLUDED_MAJOR_CHAINS = (
    "loblaws", "walmart", "metro", "sobeys", "nofrills", "no frills",
    "costco", "superstore", "food basics", "freshco", "longo's", "farm boy",
    "whole foods", "t&t", "shoppers drug", "giant tiger",
)

AFRICAN_SIGNALS = (
    "african", "nigerian", "ghana", "ghanaian", "ethiopian", "somali", "kenyan",
    "congolese", "cameroon", "senegal", "west african", "east african", "caribbean",
    "jollof", "egusi", "plantain", "injera", "fufu", "suya", "mychopchop", "chopchop",
)

# region_focus values that indicate a real African grocery (not generic SEO)
SPECIFIC_AFRICAN_REGIONS = (
    "west african", "east african", "south african", "central african",
    "nigerian", "ghanaian", "ethiopian", "somali", "senegalese", "kenyan",
    "congolese", "cameroonian", "caribbean",
)

STRONG_AFRICAN_DESC_PHRASES = (
    "african groc", "african food", "african market", "african restaurant",
    "african essentials", "authentic african", "west african", "east african",
    "south african", "nigerian", "ghanaian", "ethiopian", "caribbean grocery",
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


def search_for_city(category: str, city: str) -> list[dict]:
    """
    Run Maps-biased search first, then a general query. Maps place URLs are
    sorted to the front of the result list.
    """
    city_name = city.split(",")[0].strip()
    province = city.split(",")[1].strip() if "," in city else ""

    merged: dict[str, dict] = {}

    if MAPS_SEARCH_ENABLED:
        maps_queries = [
            f"{category} {city_name} {province} site:google.com/maps",
            f'"{category}" {city_name} {province} "google.com/maps/place"',
        ]
        for maps_query in maps_queries:
            maps_query = maps_query.strip()
            print(f"  🗺️  Maps search: {maps_query}")
            for row in search(maps_query, num_results=MAPS_SEARCH_RESULTS):
                merged[row["url"]] = row

    general_query = f'"{category}" {city_name} {province} Canada'.strip()
    print(f"  🔍 Web search: {general_query}")
    for row in search(general_query, num_results=8):
        merged.setdefault(row["url"], row)

    results = [
        r for r in merged.values()
        if not (
            "/maps/place/" in r["url"].lower()
            and not is_google_maps_place(r["url"])
        )
    ]
    results.sort(key=_result_sort_key)
    maps_count = sum(1 for r in results if is_google_maps_place(r["url"]))
    print(f"  Found {len(results)} URLs ({maps_count} Google Maps places)")
    return results


def _result_sort_key(row: dict) -> tuple[int, int]:
    """Maps places first, then likely store sites, then everything else."""
    url = row.get("url", "")
    title = row.get("title", "")
    if is_google_maps_place(url):
        return (0, 0)
    if is_blocked_url(url):
        return (2, 0)
    lower = url.lower()
    score = 1
    if "african" in lower or "african" in title.lower():
        score = 0
    if any(p in lower for p in ("/blog/", "/thread/", "/documentation", "/collections/")):
        score += 1
    return (1, score)


# ── Step 2: Filter URLs ────────────────────────────────────────────────────────

def is_blocked_url(url: str) -> bool:
    """Block junk domains; allow Google Maps /place/ listings only."""
    lower = url.lower()
    if is_google_maps_place(url):
        return False
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
    if not url or not url.strip() or is_google_maps_place(url):
        return False
    return not is_blocked_url(url)


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


def infer_city_from_address(address: str, aliases: frozenset[str]) -> Optional[str]:
    """Match a GTA (or search-area) city name embedded in a street address."""
    addr = address.lower()
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", addr):
            return alias.title()
    return None


def apply_address_city(store: StoreInfo, city_hint: str) -> None:
    """Prefer the city parsed from a street address over marketing copy."""
    key = city_hint.strip().lower()
    aliases = CITY_SEARCH_ALIASES.get(key)
    if not aliases or not store.address:
        return
    inferred = infer_city_from_address(store.address, aliases)
    if inferred:
        store.city = inferred


def align_city_with_search(store: StoreInfo, city_hint: str) -> bool:
    """
    Keep listings tied to the city being crawled.
    Online retailers based elsewhere may use the search city if they serve that area.
    """
    key = city_hint.strip().lower()
    aliases = CITY_SEARCH_ALIASES.get(key)
    hint_city = city_hint.split(",")[0].strip()
    hint_lower = hint_city.lower()

    apply_address_city(store, city_hint)

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
        if any(
            term in desc
            for term in ("online", "canada", "delivery", "ship", "nationwide")
        ):
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
    if any(chain in name_lower for chain in EXCLUDED_MAJOR_CHAINS):
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

    apply_address_city(store, city_hint)

    if not store.name or len(store.name) < 3:
        print(f"  [extract] Extracted name too short — skipping")
        return False

    store.source_url = source_url
    if not store.city:
        store.city = city_hint.split(",")[0].strip()

    if _is_store_website(source_url) and not store.website:
        store.website = source_url

    if not align_city_with_search(store, city_hint):
        return False

    if store_exists(store.name, store.city):
        print(f"  [save] Already exists: {store.name} ({store.city}) — skipped")
        return False

    if not is_relevant_african_store(store):
        print(f"  [save] Not African-focused or excluded chain — skipped ({store.name})")
        return False

    if not store_meets_quality(store, source_url):
        print(
            f"  [save] No address/phone/website — skipped "
            f"(STORE_CONTACT_RULE={STORE_CONTACT_RULE})"
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
        print(f"  No search results returned.")
        return 0

    saved = 0
    attempted = 0

    for result in results:
        if attempted >= MAX_RESULTS_PER_QUERY:
            break

        url = result["url"]
        title = result["title"]
        snippet = result["snippet"]

        print(f"\n  → {title[:60]}")
        print(f"    {url[:80]}")

        if is_blocked_url(url):
            print(f"  [skip] Blocked domain")
            continue

        attempted += 1

        if is_google_maps_place(url):
            if process_maps_place(title, snippet, url, city):
                saved += 1
            continue

        text = scrape(url)
        if text and extract_and_save(text, city, url):
            saved += 1
        else:
            print(f"  [skip] Scrape failed or no usable content")

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
            print(f"\n{'='*60}")
            print(f"[{completed}/{total_tasks}] {query} in {city}")
            print(f"{'='*60}")
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