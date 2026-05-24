#!/usr/bin/env python3
"""One-time copy of stores from local SQLite into MongoDB Atlas."""

import os
import sys

# Force Mongo target even if .env also has other defaults
os.environ.setdefault("STORAGE_BACKEND", "mongodb")

if not os.getenv("MONGODB_URI"):
    print("Set MONGODB_URI in .env first.")
    sys.exit(1)

from models import StoreInfo
from storage_sqlite import get_all_stores as sqlite_get_all
from storage_mongo import init_db, save_store


def main() -> None:
    init_db()
    rows = sqlite_get_all()
    if not rows:
        print("No rows in SQLite.")
        return

    saved = 0
    for row in rows:
        store = StoreInfo(
            name=row["name"],
            category=row.get("category") or "Other",
            region_focus=row.get("region_focus"),
            address=row.get("address"),
            city=row.get("city"),
            province=row.get("province"),
            postal_code=row.get("postal_code"),
            phone=row.get("phone"),
            website=row.get("website"),
            email=row.get("email"),
            hours=row.get("hours"),
            description=row.get("description") or "",
            products_and_specialties=row.get("products_and_specialties"),
            source_url=row.get("source_url"),
        )
        ok, msg = save_store(store)
        if ok and msg.startswith("Saved:"):
            saved += 1
        print(msg)

    print(f"\nDone. Inserted {saved} new document(s) into MongoDB.")


if __name__ == "__main__":
    main()
