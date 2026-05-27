# storage_mongo.py — MongoDB Atlas backend for store directory data.

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from config import MONGODB_COLLECTION, MONGODB_DB_NAME, MONGODB_URI
from models import StoreInfo

_client: MongoClient | None = None


def _get_collection() -> Collection:
    global _client
    if not MONGODB_URI:
        msg = "MONGODB_URI is not set. Add it to .env or GitHub Actions secrets."
        raise ValueError(msg)
    if _client is None:
        _client = MongoClient(MONGODB_URI)
    return _client[MONGODB_DB_NAME][MONGODB_COLLECTION]


def _keys(name: str, city: Optional[str]) -> tuple[str, str]:
    return name.strip().lower(), (city or "").strip().lower()


def _store_to_doc(store: StoreInfo) -> dict:
    name_lower, city_lower = _keys(store.name, store.city)
    return {
        "name": store.name,
        "name_lower": name_lower,
        "category": store.category,
        "region_focus": store.region_focus,
        "address": store.address,
        "city": store.city,
        "city_lower": city_lower,
        "province": store.province,
        "postal_code": store.postal_code,
        "phone": store.phone,
        "website": store.website,
        "email": store.email,
        "hours": store.hours,
        "description": store.description,
        "products_and_specialties": store.products_and_specialties or [],
        "source_url": store.source_url,
        "created_at": datetime.now(timezone.utc),
    }


def _doc_to_dict(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id", "name_lower", "city_lower")}
    out["id"] = str(doc["_id"])
    created = doc.get("created_at")
    if isinstance(created, datetime):
        out["created_at"] = created.isoformat()
    return out


def init_db() -> None:
    """Ensure indexes exist and verify Atlas connectivity."""
    coll = _get_collection()
    coll.create_index(
        [("name_lower", ASCENDING), ("city_lower", ASCENDING)],
        unique=True,
        name="uniq_name_city",
    )
    coll.create_index([("province", ASCENDING), ("city", ASCENDING), ("name", ASCENDING)])
    coll.database.client.admin.command("ping")


def save_store(store: StoreInfo) -> tuple[bool, str]:
    doc = _store_to_doc(store)
    coll = _get_collection()
    try:
        result = coll.update_one(
            {"name_lower": doc["name_lower"], "city_lower": doc["city_lower"]},
            {"$setOnInsert": doc},
            upsert=True,
        )
        if result.upserted_id is not None:
            return True, f"Saved: {store.name} ({store.city})"
        return True, f"Already in database: {store.name} ({store.city})"
    except DuplicateKeyError:
        return True, f"Already in database: {store.name} ({store.city})"
    except Exception as e:
        return False, f"DB error: {e}"


def get_all_stores() -> List[dict]:
    coll = _get_collection()
    cursor = coll.find().sort([("province", 1), ("city", 1), ("name", 1)])
    return [_doc_to_dict(doc) for doc in cursor]


def get_stores_by_city(city: str) -> List[dict]:
    coll = _get_collection()
    cursor = coll.find({"city_lower": city.strip().lower()}).sort("name", 1)
    return [_doc_to_dict(doc) for doc in cursor]


def store_exists(name: str, city: Optional[str]) -> bool:
    name_lower, city_lower = _keys(name, city)
    return (
        _get_collection().find_one(
            {"name_lower": name_lower, "city_lower": city_lower},
            {"_id": 1},
        )
        is not None
    )


def get_stats() -> dict:
    coll = _get_collection()
    total = coll.count_documents({})
    by_city = list(
        coll.aggregate(
            [
                {"$group": {"_id": "$city", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
        )
    )
    by_category = list(
        coll.aggregate(
            [
                {"$group": {"_id": "$category", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
        )
    )
    return {
        "total": total,
        "by_city": [{"city": r["_id"], "count": r["count"]} for r in by_city],
        "by_category": [{"category": r["_id"], "count": r["count"]} for r in by_category],
    }
