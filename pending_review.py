# pending_review.py — Human-in-the-loop review queue for low-confidence
# validator output. Mirrors crawl_tracker.py's connection pattern: its own
# MongoDB collection, separate from the main `stores` collection, with the
# same defensive _get_collection() / PyMongoError handling.
#
# WHY THIS EXISTS:
#   The Validator Agent's quality bar was previously binary: a candidate
#   store either had enough info to pass (accept) or didn't (silently
#   dropped). That's fine for clear-cut cases, but loses real stores where
#   the source text was ambiguous — a phone number formatted oddly, a city
#   the model had to infer rather than read directly, a name that might be
#   a chain location vs. a duplicate. Rather than guessing, the Validator
#   now flags these as low-confidence and routes them here instead of
#   discarding them outright. A human (you, via the /ops dashboard once
#   built) can then approve (→ saved to the main stores collection) or
#   reject (→ discarded with a reason) each one.
#
#   This is the same HITL correction pattern used in the Igbo RAG project's
#   Open WebUI correction system — flag uncertain output for human review
#   rather than either auto-accepting or auto-discarding it.
#
# USAGE:
#   from pending_review import record_pending_review, get_pending_reviews
#   record_pending_review(store_dict, city, category, reason="low confidence: city inferred")
#   reviews = get_pending_reviews(status="pending")

from __future__ import annotations

from datetime import UTC, datetime

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from config import MONGODB_DB_NAME, MONGODB_URI

PENDING_REVIEW_COLLECTION = "pending_review"

_client: MongoClient | None = None


def _ensure_indexes(coll: Collection) -> None:
    """Create pending_review indexes (idempotent — safe to call on every access)."""
    try:
        coll.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
        coll.create_index([("city", ASCENDING), ("status", ASCENDING)])
    except PyMongoError as e:
        print(f"  [pending_review] Warning: index creation failed ({e})")


def _get_collection() -> Collection | None:
    global _client
    if not MONGODB_URI:
        print("  [pending_review] Warning: MONGODB_URI not set — review queue disabled")
        return None
    try:
        if _client is None:
            _client = MongoClient(MONGODB_URI)
        coll = _client[MONGODB_DB_NAME][PENDING_REVIEW_COLLECTION]
        _ensure_indexes(coll)
        return coll
    except PyMongoError as e:
        print(f"  [pending_review] Warning: MongoDB connection failed ({e})")
        return None


def record_pending_review(
    store: dict,
    city: str,
    category: str,
    reason: str,
    run_id: str = "local",
) -> str | None:
    """
    Write a low-confidence candidate store to the review queue.

    Args:
        store: the parsed store dict (same shape the Validator would have
            emitted to validated_stores — name, category, city, address, etc.)
        city: the crawl city this candidate came from
        category: the crawl category/search term this candidate came from
        reason: human-readable explanation of why confidence was low
            (e.g. "city inferred from context, not stated directly")
        run_id: crawl run identifier, for tracing back to a specific CI run

    Returns the inserted document's id as a string, or None if the write
    failed (e.g. MONGODB_URI not configured) — non-fatal, matches the
    defensive pattern used elsewhere (crawl_tracker, save_store_to_db).
    """
    coll = _get_collection()
    if coll is None:
        return None

    doc = {
        "store": store,
        "city": city,
        "category": category,
        "reason": reason,
        "run_id": run_id,
        "status": "pending",  # pending | approved | rejected
        "created_at": datetime.now(UTC),
        "reviewed_at": None,
        "reviewed_by": None,
    }
    try:
        result = coll.insert_one(doc)
        print(f"  [pending_review] Flagged for review: {store.get('name', '?')} ({reason})")
        return str(result.inserted_id)
    except PyMongoError as e:
        print(f"  [pending_review] Warning: failed to record review ({e})")
        return None


def get_pending_reviews(status: str = "pending", limit: int = 100) -> list[dict]:
    """
    Return review queue entries, most recent first.

    Args:
        status: filter by status — "pending" (default), "approved", "rejected",
            or "all" to return every status.
        limit: max entries to return.
    """
    coll = _get_collection()
    if coll is None:
        return []

    query: dict = {} if status == "all" else {"status": status}
    try:
        cursor = coll.find(query, sort=[("created_at", -1)], limit=limit)
        results = []
        for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)
        return results
    except PyMongoError as e:
        print(f"  [pending_review] Warning: failed to read review queue ({e})")
        return []


def approve_review(review_id: str, reviewed_by: str = "unknown") -> tuple[bool, str]:
    """
    Approve a pending review: marks it approved and saves the store to the
    main stores collection via storage.save_store. Returns (success, message).
    """
    from bson import ObjectId

    from models import StoreInfo
    from storage import save_store

    coll = _get_collection()
    if coll is None:
        return False, "Review queue unavailable (MONGODB_URI not set)"

    try:
        doc = coll.find_one({"_id": ObjectId(review_id)})
    except PyMongoError as e:
        return False, f"Failed to look up review: {e}"

    if doc is None:
        return False, f"Review {review_id} not found"
    if doc.get("status") != "pending":
        return False, f"Review {review_id} already {doc.get('status')}"

    try:
        store = StoreInfo(**doc["store"])
    except Exception as e:
        return False, f"Stored candidate failed schema validation: {e}"

    success, message = save_store(store)
    if not success:
        return False, f"Save failed: {message}"

    try:
        coll.update_one(
            {"_id": ObjectId(review_id)},
            {
                "$set": {
                    "status": "approved",
                    "reviewed_at": datetime.now(UTC),
                    "reviewed_by": reviewed_by,
                }
            },
        )
    except PyMongoError as e:
        # Store was saved successfully even if this status update fails —
        # don't report failure for what is fundamentally a success.
        print(f"  [pending_review] Warning: saved store but failed to update review status ({e})")

    return True, f"Approved and saved: {message}"


def reject_review(
    review_id: str, reviewed_by: str = "unknown", reason: str = ""
) -> tuple[bool, str]:
    """Reject a pending review: marks it rejected, does not save the store."""
    from bson import ObjectId

    coll = _get_collection()
    if coll is None:
        return False, "Review queue unavailable (MONGODB_URI not set)"

    try:
        result = coll.update_one(
            {"_id": ObjectId(review_id), "status": "pending"},
            {
                "$set": {
                    "status": "rejected",
                    "reviewed_at": datetime.now(UTC),
                    "reviewed_by": reviewed_by,
                    "rejection_reason": reason,
                }
            },
        )
    except PyMongoError as e:
        return False, f"Failed to reject review: {e}"

    if result.matched_count == 0:
        return False, f"Review {review_id} not found or not pending"

    return True, f"Rejected review {review_id}"


def get_review_stats() -> dict:
    """Counts by status — for the ops dashboard summary card."""
    coll = _get_collection()
    if coll is None:
        return {"pending": 0, "approved": 0, "rejected": 0, "total": 0}

    try:
        pending = coll.count_documents({"status": "pending"})
        approved = coll.count_documents({"status": "approved"})
        rejected = coll.count_documents({"status": "rejected"})
        return {
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "total": pending + approved + rejected,
        }
    except PyMongoError as e:
        print(f"  [pending_review] Warning: failed to compute stats ({e})")
        return {"pending": 0, "approved": 0, "rejected": 0, "total": 0}
