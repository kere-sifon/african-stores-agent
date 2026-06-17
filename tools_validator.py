# tools_validator.py
# ─────────────────────────────────────────────────────────────────────────────
# VALIDATOR AGENT tool set — strictly bounded to existence checking only.
# The Validator Agent can READ from the database (to check duplicates) but
# has NO write access. It cannot call save_store_to_db or get_database_stats.
#
# This boundary is architecturally important: validation is stateless from
# the write perspective. If the validator fails, no data is corrupted.
# ─────────────────────────────────────────────────────────────────────────────

from tools import check_store_exists


def get_validator_tools() -> list:
    """
    Return the bounded tool set for the Validator Agent.
    Read-only: existence check only.
    Intentionally excludes: search_for_stores, scrape_page, save_store_to_db, get_database_stats.
    """
    return [
        check_store_exists,
    ]
