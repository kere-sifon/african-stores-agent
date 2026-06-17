# tools_storage.py
# ─────────────────────────────────────────────────────────────────────────────
# STORAGE AGENT tool set — strictly bounded to MongoDB write operations.
# The Storage Agent cannot search the web or check existence (the Validator
# already did that). Its only job is to write pre-validated stores.
#
# get_database_stats is included so the Storage Agent can confirm totals
# after saving — this is the per-agent evaluation hook.
# ─────────────────────────────────────────────────────────────────────────────

from tools import get_database_stats, save_store_to_db


def get_storage_tools() -> list:
    """
    Return the bounded tool set for the Storage Agent.
    Write + stats only.
    Intentionally excludes: search_for_stores, scrape_page, check_store_exists.
    """
    return [
        save_store_to_db,
        get_database_stats,
    ]
