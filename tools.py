# tools.py
# ─────────────────────────────────────────────────────────────────────────────
# LangChain TOOLS are the hands of your agent. Each tool is a Python function
# decorated with @tool. The agent reads the docstring to decide *when* to call
# each tool, and the function signature defines the *input schema*.
#
# Key LangChain concept:
#   The agent does NOT call tools directly — it outputs a JSON blob saying
#   "call tool X with args Y", and the AgentExecutor handles the actual call.
#   This is the ReAct loop: Reason → Act → Observe → Reason → ...
# ─────────────────────────────────────────────────────────────────────────────

import time
import json
import re
import requests
from bs4 import BeautifulSoup
from typing import Optional

# LangChain tool decorator — turns any Python function into a tool the agent
# can discover and invoke.
from langchain_core.tools import tool

# LangChain's built-in DuckDuckGo search tool (no API key required).
from langchain_community.tools import DuckDuckGoSearchResults

from config import CRAWL_DELAY_SECONDS
from models import StoreInfo
from pipeline import store_meets_quality
from storage import save_store, store_exists, get_stats

# ── Utility ───────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

_ddg_search = DuckDuckGoSearchResults(num_results=5, output_format="list")


def _clean_text(html: str, max_chars: int = 4000) -> str:
    """Strip HTML tags and collapse whitespace. Truncate to stay inside context window."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# ── Tool 1: Web search ────────────────────────────────────────────────────────

@tool
def search_for_stores(query: str) -> str:
    """
    Search the web for African stores in Canada using the given query string.
    Returns a list of URLs and snippets. Use queries like:
    'African grocery store Toronto Canada' or 'Nigerian restaurant Calgary'.
    """
    try:
        results = _ddg_search.invoke(query)
        # results is a list of dicts: [{snippet, title, link}, ...]
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"TITLE: {r.get('title', '')}")
            lines.append(f"URL: {r.get('link', '')}")
            lines.append(f"SNIPPET: {r.get('snippet', '')}")
            lines.append("---")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"


# ── Tool 2: Web scraper ───────────────────────────────────────────────────────

@tool
def scrape_page(url: str) -> str:
    """
    Fetch and return the cleaned text content of a web page.
    Use this after searching to get full details about a store from its website
    or a directory listing page. Returns plain text, truncated to 4000 chars.
    """
    try:
        time.sleep(CRAWL_DELAY_SECONDS)  # be polite
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return _clean_text(resp.text)
    except requests.exceptions.HTTPError as e:
        return f"HTTP error scraping {url}: {e}"
    except Exception as e:
        return f"Error scraping {url}: {e}"


# ── Tool 3: Save a store ──────────────────────────────────────────────────────

@tool
def save_store_to_db(store_json: str) -> str:
    """
    Save a store to the database. Input must be a valid JSON string matching
    the StoreInfo schema. Required fields: name, category, description.
    Optional but important: city, province, address, phone, website.

    Example input:
    {
      "name": "Lagos Market",
      "category": "Grocery",
      "region_focus": "West African",
      "city": "Toronto",
      "province": "Ontario",
      "address": "123 Main St",
      "phone": "416-555-0123",
      "description": "A family-run West African grocery...",
      "source_url": "https://example.com"
    }
    """
    try:
        data = json.loads(store_json)
        store = StoreInfo(**data)

        # Skip if we already have this store
        if store_exists(store.name, store.city):
            return f"Already in database: {store.name} ({store.city}) — skipped."

        if not store_meets_quality(store, store.source_url or ""):
            return "Skipped: needs address, phone, or store website."

        success, message = save_store(store)
        return message
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"
    except Exception as e:
        return f"Error saving store: {e}"


# ── Tool 4: Check database stats ──────────────────────────────────────────────

@tool
def get_database_stats(_: str = "") -> str:
    """
    Return a summary of stores already collected in the database.
    Use this to check progress, see which cities have been covered, and
    avoid re-scraping stores already saved.
    """
    stats = get_stats()
    lines = [f"Total stores in database: {stats['total']}", ""]
    if stats["by_city"]:
        lines.append("By city:")
        for row in stats["by_city"]:
            lines.append(f"  {row['city']}: {row['count']}")
    if stats["by_category"]:
        lines.append("\nBy category:")
        for row in stats["by_category"]:
            lines.append(f"  {row['category']}: {row['count']}")
    return "\n".join(lines)


# ── Tool 5: Check if store already exists ─────────────────────────────────────

@tool
def check_store_exists(name_and_city: str) -> str:
    """
    Check if a store is already in the database before scraping it.
    Input format: 'Store Name, City' (comma-separated).
    Returns 'exists' or 'not found'.
    """
    parts = name_and_city.split(",", 1)
    name = parts[0].strip()
    city = parts[1].strip() if len(parts) > 1 else None
    if store_exists(name, city):
        return f"EXISTS: {name} in {city} is already saved. Skip it."
    return f"NOT FOUND: {name} in {city} is not in the database yet."


# ── Tool registry ─────────────────────────────────────────────────────────────

def get_all_tools():
    """Return all tools to register with the agent."""
    return [
        search_for_stores,
        scrape_page,
        save_store_to_db,
        get_database_stats,
        check_store_exists,
    ]
