# storage_sqlite.py — local SQLite backend (default when MONGODB_URI is unset).

import json
import sqlite3
from typing import List, Optional

from config import DB_PATH
from models import StoreInfo


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
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
                products_and_specialties TEXT,
                source_url              TEXT,
                created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, city)
            )
            """
        )
        conn.commit()


def save_store(store: StoreInfo) -> tuple[bool, str]:
    try:
        with get_connection() as conn:
            # FIX: use cursor.rowcount to distinguish a real insert from a
            # silently-ignored duplicate. INSERT OR IGNORE always "succeeds"
            # (no exception) even when the UNIQUE constraint fires and nothing
            # is written — rowcount == 0 in that case.
            cursor = conn.execute(
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

        if cursor.rowcount == 0:
            return True, f"Already in database: {store.name} ({store.city})"
        return True, f"Saved: {store.name} ({store.city})"
    except Exception as e:
        return False, f"DB error: {e}"


def get_all_stores() -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stores ORDER BY province, city, name"
        ).fetchall()
    stores = []
    for row in rows:
        d = dict(row)
        d["products_and_specialties"] = json.loads(
            d.get("products_and_specialties") or "[]"
        )
        stores.append(d)
    return stores


def get_stores_by_city(city: str) -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stores WHERE LOWER(city) = LOWER(?) ORDER BY name",
            (city,),
        ).fetchall()
    return [_row_to_dict(dict(r)) for r in rows]


def _row_to_dict(d: dict) -> dict:
    d["products_and_specialties"] = json.loads(
        d.get("products_and_specialties") or "[]"
    )
    return d


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
