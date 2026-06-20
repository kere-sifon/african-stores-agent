# crawl_tracker.py — Province crawl history in MongoDB (crawl_history collection).

from __future__ import annotations

from datetime import UTC, datetime

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from config import MONGODB_DB_NAME, MONGODB_URI

CRAWL_HISTORY_COLLECTION = "crawl_history"

_client: MongoClient | None = None


def _ensure_indexes(coll: Collection) -> None:
    """Create crawl_history indexes (idempotent — safe to call on every access)."""
    try:
        coll.create_index(
            [("province", ASCENDING), ("year", ASCENDING), ("week_number", ASCENDING)],
            unique=True,
            name="uniq_province_year_week",
        )
        coll.create_index([("province", ASCENDING), ("last_crawled_at", ASCENDING)])
    except PyMongoError as e:
        print(f"  [crawl_tracker] Warning: index creation failed ({e})")


def _get_collection() -> Collection | None:
    global _client
    if not MONGODB_URI:
        print("  [crawl_tracker] Warning: MONGODB_URI not set — tracker disabled")
        return None
    try:
        if _client is None:
            _client = MongoClient(MONGODB_URI)
        coll = _client[MONGODB_DB_NAME][CRAWL_HISTORY_COLLECTION]
        _ensure_indexes(coll)
        return coll
    except PyMongoError as e:
        print(f"  [crawl_tracker] Warning: MongoDB connection failed ({e})")
        return None


def record_province_crawl(
    province: str,
    stores_saved: int,
    cities_crawled: list[str],
    week_number: int,
    run_id: str = "local",
    eval_results: list[dict] | None = None,
    usage_summary: dict | None = None,
) -> None:
    """
    Upsert crawl record for this province+year+week.
    Sets last_crawled_at to datetime.utcnow().

    If eval_results is provided (list of {"city", "category", "scores"} dicts
    from eval_agents.evaluate_run()), an aggregated eval_summary is computed
    and stored alongside the crawl record — this is what powers per-province
    eval trend queries (e.g. "search precision over the last 10 crawls of
    Ontario") without needing a separate eval datastore.

    If usage_summary is provided (the dict from
    cost_tracking.aggregate_crawl_usage()), it's stored alongside as
    token_usage_summary — same trend-query pattern, for "cost per crawl
    over time" rather than building a separate billing datastore.
    """
    coll = _get_collection()
    if coll is None:
        return

    now = datetime.now(UTC)
    year = now.year
    doc = {
        "province": province,
        "last_crawled_at": now,
        "stores_saved": stores_saved,
        "cities_crawled": cities_crawled,
        "week_number": week_number,
        "year": year,
        "run_id": run_id,
    }

    if eval_results is not None:
        from eval_agents import aggregate_run_evals

        doc["eval_summary"] = aggregate_run_evals(eval_results)

    if usage_summary is not None:
        doc["token_usage_summary"] = usage_summary

    try:
        coll.update_one(
            {"province": province, "year": year, "week_number": week_number},
            {"$set": doc},
            upsert=True,
        )
        print(
            f"  [crawl_tracker] Recorded crawl: {province} "
            f"(week {week_number}/{year}, +{stores_saved} stores)"
        )
    except PyMongoError as e:
        print(f"  [crawl_tracker] Warning: failed to record crawl ({e})")


def get_province_last_crawled(province: str) -> dict | None:
    """Return most recent crawl record for province, or None if never crawled."""
    coll = _get_collection()
    if coll is None:
        return None
    try:
        return coll.find_one({"province": province}, sort=[("last_crawled_at", -1)])
    except PyMongoError as e:
        print(f"  [crawl_tracker] Warning: failed to read crawl history ({e})")
        return None


def get_crawl_coverage() -> list[dict]:
    """
    Return coverage summary for ALL provinces in PROVINCE_ROTATION.
    Each dict: {province, last_crawled_at, days_since_crawl, stores_saved}.
    """
    from provinces import PROVINCE_ROTATION

    coll = _get_collection()
    now = datetime.now(UTC)
    results: list[dict] = []

    for province in PROVINCE_ROTATION:
        entry: dict = {
            "province": province,
            "last_crawled_at": None,
            "days_since_crawl": None,
            "stores_saved": None,
        }
        if coll is None:
            results.append(entry)
            continue
        try:
            record = coll.find_one({"province": province}, sort=[("last_crawled_at", -1)])
        except PyMongoError as e:
            print(f"  [crawl_tracker] Warning: failed to read {province} ({e})")
            results.append(entry)
            continue

        if record:
            crawled_at = record.get("last_crawled_at")
            entry["last_crawled_at"] = crawled_at
            entry["stores_saved"] = record.get("stores_saved")
            if crawled_at:
                if crawled_at.tzinfo is None:
                    crawled_at = crawled_at.replace(tzinfo=UTC)
                entry["days_since_crawl"] = (now - crawled_at).days
        results.append(entry)

    return results


def get_eval_trend(province: str | None = None, limit: int = 20) -> list[dict]:
    """
    Return recent crawl records with eval_summary populated, most recent first.
    Pass province to filter to a single province; omit for all provinces
    (useful for an "eval trend over time" chart on the ops dashboard).

    Only records that actually have an eval_summary are returned — older
    crawl_history records predating this feature won't have one.
    """
    coll = _get_collection()
    if coll is None:
        return []

    query: dict = {"eval_summary": {"$exists": True}}
    if province:
        query["province"] = province

    try:
        cursor = coll.find(query, sort=[("last_crawled_at", -1)], limit=limit)
        return list(cursor)
    except PyMongoError as e:
        print(f"  [crawl_tracker] Warning: failed to read eval trend ({e})")
        return []


def get_cost_trend(province: str | None = None, limit: int = 20) -> list[dict]:
    """
    Return recent crawl records with token_usage_summary populated, most
    recent first. Pass province to filter to a single province; omit for
    all provinces (useful for a "cost over time" chart on the ops dashboard).

    Only records that actually have a token_usage_summary are returned —
    older crawl_history records predating this feature won't have one.
    """
    coll = _get_collection()
    if coll is None:
        return []

    query: dict = {"token_usage_summary": {"$exists": True}}
    if province:
        query["province"] = province

    try:
        cursor = coll.find(query, sort=[("last_crawled_at", -1)], limit=limit)
        return list(cursor)
    except PyMongoError as e:
        print(f"  [crawl_tracker] Warning: failed to read cost trend ({e})")
        return []


def was_crawled_this_week(province: str) -> bool:
    """Return True if province was crawled in the current ISO week and year."""
    coll = _get_collection()
    if coll is None:
        return False

    now = datetime.now(UTC)
    week_number = now.isocalendar()[1]
    year = now.year
    try:
        record = coll.find_one(
            {"province": province, "week_number": week_number, "year": year},
            {"_id": 1},
        )
        return record is not None
    except PyMongoError as e:
        print(f"  [crawl_tracker] Warning: was_crawled_this_week check failed ({e})")
        return False
