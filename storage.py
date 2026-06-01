# storage.py — storage facade (SQLite or MongoDB Atlas via STORAGE_BACKEND).

import importlib

from config import STORAGE_BACKEND

_backend = importlib.import_module(
    "storage_mongo" if STORAGE_BACKEND == "mongodb" else "storage_sqlite"
)

get_all_stores = _backend.get_all_stores
get_stats = _backend.get_stats
get_stores_by_city = _backend.get_stores_by_city
init_db = _backend.init_db
save_store = _backend.save_store
store_exists = _backend.store_exists

__all__ = [
    "get_all_stores",
    "get_stats",
    "get_stores_by_city",
    "init_db",
    "save_store",
    "store_exists",
    "storage_summary",
]


def storage_summary() -> str:
    """Human-readable backend label for logs."""
    if STORAGE_BACKEND == "mongodb":
        from config import MONGODB_COLLECTION, MONGODB_DB_NAME

        return f"backend=mongodb db={MONGODB_DB_NAME} collection={MONGODB_COLLECTION}"
    from config import DB_PATH

    return f"backend=sqlite path={DB_PATH}"
