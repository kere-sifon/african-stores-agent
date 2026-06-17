# tools_search.py
# ─────────────────────────────────────────────────────────────────────────────
# SEARCH AGENT tool set — strictly bounded to web search and page scraping.
# The Search Agent has NO access to database tools. This boundary is enforced
# by only passing get_search_tools() to the Search Agent's LLM.bind_tools() call.
# ─────────────────────────────────────────────────────────────────────────────

from tools import scrape_page, search_for_stores


def get_search_tools() -> list:
    """
    Return the bounded tool set for the Search Agent.
    Intentionally excludes: save_store_to_db, check_store_exists, get_database_stats.
    The Search Agent cannot write to or read from the database.
    """
    return [
        search_for_stores,
        scrape_page,
    ]
