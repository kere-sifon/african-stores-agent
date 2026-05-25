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
import json
from typing import Optional

from langchain_community.tools import DuckDuckGoSearchResults

from extractor import extract_store_info
from storage import init_db, save_store, store_exists, get_stats
from config import (
    TARGET_CITIES,
    SEARCH_QUERIES,
    MAX_RESULTS_PER_QUERY,
    CRAWL_DELAY_SECONDS,
    STORE_CONTACT_RULE,
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
    "google.com", "google.ca", "yelp.com",
    "twitter.com", "linkedin.com", "reddit.com",
    "narcity.com", "blogto.com",
]

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

_ddg = DuckDuckGoSearchResults(num_results=8, output_format="list")


# ── Step 1: Search ─────────────────────────────────────────────────────────────

def search(query: str) -> list[dict]:
    """Call DuckDuckGo and return list of {title, url, snippet}."""
    try:
        time.sleep(CRAWL_DELAY_SECONDS)
        results = _ddg.invoke(query)
        return [
            {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
            for r in results
            if r.get("link")
        ]
    except Exception as e:
        print(f"  [search] Error: {e}")
        return []


# ── Step 2: Filter URLs ────────────────────────────────────────────────────────

def is_scrapeable(url: str) -> bool:
    """Return False for domains that block scrapers or aren't store pages."""
    for domain in BLOCKED_DOMAINS:
        if domain in url:
            return False
    return True


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
    return not any(domain in url for domain in BLOCKED_DOMAINS)


def is_relevant_african_store(store: StoreInfo) -> bool:
    """Filter out major chains and pages with no African focus."""
    name_lower = (store.name or "").lower()
    if any(chain in name_lower for chain in EXCLUDED_MAJOR_CHAINS):
        return False

    parts = [store.name or "", store.description or "", store.region_focus or ""]
    if store.products_and_specialties:
        parts.extend(store.products_and_specialties)
    blob = " ".join(parts).lower()
    return any(signal in blob or signal in name_lower for signal in AFRICAN_SIGNALS)


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

    if not store.name or len(store.name) < 3:
        print(f"  [extract] Extracted name too short — skipping")
        return False

    store.source_url = source_url
    if not store.city:
        store.city = city_hint.split(",")[0].strip()

    if _is_store_website(source_url) and not store.website:
        store.website = source_url

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
    query = f"{category} {city} Canada"
    print(f"\n  🔍 Searching: {query}")
    results = search(query)

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

        if not is_scrapeable(url):
            print(f"  [skip] Blocked domain — not saving from snippet")
            continue

        attempted += 1
        text = scrape(url)

        if text:
            if extract_and_save(text, city, url):
                saved += 1
        else:
            print(f"  [skip] Scrape failed — no snippet fallback (low quality)")

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