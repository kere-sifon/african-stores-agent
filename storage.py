# storage.py — storage facade (SQLite or MongoDB Atlas via STORAGE_BACKEND).

from config import STORAGE_BACKEND

if STORAGE_BACKEND == "mongodb":
    from storage_mongo import (  # noqa: F401
        get_all_stores,
        get_stats,
        get_stores_by_city,
        init_db,
        save_store,
        store_exists,
    )
else:
    from storage_sqlite import (  # noqa: F401
        get_all_stores,
        get_stats,
        get_stores_by_city,
        init_db,
        save_store,
        store_exists,
    )


def storage_summary() -> str:
    """Human-readable backend label for logs."""
    if STORAGE_BACKEND == "mongodb":
        from config import MONGODB_COLLECTION, MONGODB_DB_NAME

        return f"backend=mongodb db={MONGODB_DB_NAME} collection={MONGODB_COLLECTION}"
    from config import DB_PATH

    return f"backend=sqlite path={DB_PATH}"
