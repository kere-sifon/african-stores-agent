# storage.py
# ─────────────────────────────────────────────────────────────────────────────
# Simple SQLite wrapper. The agent tools call these functions to persist
# extracted store data. SQLite is zero-config and perfect for local projects.
# ─────────────────────────────────────────────────────────────────────────────

import sqlite3
import json
from typing import Optional, List
from models import StoreInfo
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


def init_db() -> None:
    """Create the stores table if it doesn't already exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stores (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                name                    TEXT NOT NULL,
                category                TEXT,
                region_focus            TEXT,
                address                 TEXT,
                city                    TEXT,
                province                TEXT,
                postal_code             TEXT,
                phone                   TEXT,
                website                 TEXT,
                email                   TEXT,
                hours                   TEXT,
                description             TEXT,
                products_and_specialties TEXT,   -- stored as JSON array
                source_url              TEXT,
                created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, city)              -- avoid duplicates
            )
            """
        )
        conn.commit()


def save_store(store: StoreInfo) -> tuple[bool, str]:
    """
    Insert a store record. Returns (success, message).
    Uses INSERT OR IGNORE so duplicate (name, city) pairs are silently skipped.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO stores (
                    name, category, region_focus, address, city, province,
                    postal_code, phone, website, email, hours, description,
                    products_and_specialties, source_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    store.name,
                    store.category,
                    store.region_focus,
                    store.address,
                    store.city,
                    store.province,
                    store.postal_code,
                    store.phone,
                    store.website,
                    store.email,
                    store.hours,
                    store.description,
                    json.dumps(store.products_and_specialties or []),
                    store.source_url,
                ),
            )
            conn.commit()
        return True, f"Saved: {store.name} ({store.city})"
    except Exception as e:
        return False, f"DB error: {e}"


def get_all_stores() -> List[dict]:
    """Return all stores as a list of plain dicts."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stores ORDER BY province, city, name"
        ).fetchall()
    stores = []
    for row in rows:
        d = dict(row)
        d["products_and_specialties"] = json.loads(d.get("products_and_specialties") or "[]")
        stores.append(d)
    return stores


def get_stores_by_city(city: str) -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stores WHERE LOWER(city) = LOWER(?) ORDER BY name",
            (city,),
        ).fetchall()
    return [dict(r) for r in rows]


def store_exists(name: str, city: Optional[str]) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM stores WHERE LOWER(name) = LOWER(?) AND LOWER(city) = LOWER(?)",
            (name, city or ""),
        ).fetchone()
    return row is not None


def get_stats() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
        by_city = conn.execute(
            "SELECT city, COUNT(*) as count FROM stores GROUP BY city ORDER BY count DESC"
        ).fetchall()
        by_category = conn.execute(
            "SELECT category, COUNT(*) as count FROM stores GROUP BY category ORDER BY count DESC"
        ).fetchall()
    return {
        "total": total,
        "by_city": [dict(r) for r in by_city],
        "by_category": [dict(r) for r in by_category],
    }
