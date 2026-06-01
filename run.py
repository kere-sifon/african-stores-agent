#!/usr/bin/env python3
# run.py — CLI entry point
#
# Usage:
#   python run.py                   single city test (pipeline)
#   python run.py --full            full crawl (pipeline)
#   python run.py --names "Store A, Store B" [--city "Toronto, Ontario"]
#   python run.py --names-file stores.txt [--city "Toronto, Ontario"]
#   python run.py --agent           single city test (LangGraph agent)
#   python run.py --city-crawl --city "Montreal, Quebec"
#   python run.py --agent --city-crawl --city "Montreal, Quebec"
#   python run.py --agent-full      full crawl (LangGraph agent)
#   python run.py --province "Alberta"
#   python run.py --province-weekly
#   python run.py --province-schedule
#   python run.py --reset-cycle
#   python run.py --generate        build HTML site from DB
#   python run.py --stats           print DB summary

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from storage import get_stats, init_db

DEFAULT_CITY = "Toronto, Ontario"


def parse_store_names(names: str | None, names_file: str | None) -> list[str]:
    """Parse store names from a comma/newline string and/or a text file."""
    parsed: list[str] = []

    if names_file:
        path = Path(names_file)
        if not path.is_file():
            print(f"Error: names file not found: {names_file}", file=sys.stderr)
            sys.exit(1)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parsed.append(line)

    if names:
        for part in re.split(r"[\n,;]+", names):
            part = part.strip()
            if part:
                parsed.append(part)

    seen: set[str] = set()
    unique: list[str] = []
    for name in parsed:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            unique.append(name)
    return unique


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="African Stores Canada — crawl & directory")
    parser.add_argument("--full", action="store_true", help="Full pipeline crawl (all cities)")
    parser.add_argument(
        "--agent", action="store_true", help="Use LangGraph agent instead of pipeline"
    )
    parser.add_argument("--agent-full", action="store_true", help="Agent full crawl")
    parser.add_argument("--generate", action="store_true", help="Generate HTML site from DB")
    parser.add_argument("--stats", action="store_true", help="Print database stats")
    parser.add_argument(
        "--names",
        metavar="NAMES",
        help="Store names to crawl (comma, semicolon, or newline separated)",
    )
    parser.add_argument(
        "--names-file",
        metavar="PATH",
        help="File with one store name per line (# comments allowed)",
    )
    parser.add_argument(
        "--city-crawl",
        action="store_true",
        help="Crawl all store categories in the city given by --city",
    )
    parser.add_argument(
        "--city",
        default=DEFAULT_CITY,
        help=f'City for search (default: "{DEFAULT_CITY}") — use "City, Province"',
    )
    parser.add_argument(
        "--province",
        metavar="PROVINCE",
        help='Crawl all cities in a province — e.g. "Alberta"',
    )
    parser.add_argument(
        "--province-weekly",
        action="store_true",
        help="Automatically crawl this week's province per rotation schedule",
    )
    parser.add_argument(
        "--province-schedule",
        action="store_true",
        help="Print the province rotation schedule and exit",
    )
    parser.add_argument(
        "--reset-cycle",
        action="store_true",
        help="Clear crawl history to start a fresh province rotation cycle",
    )
    return parser


def run_test():
    from pipeline import run_test_pipeline

    run_test_pipeline()


def run_full():
    from pipeline import run_full_pipeline

    run_full_pipeline()
    generate()


def run_names_pipeline(store_names: list[str], city: str) -> None:
    from pipeline import run_names_pipeline as pipeline_names

    pipeline_names(store_names, city)
    generate()


def run_city_crawl(city: str, use_agent: bool) -> None:
    if use_agent:
        from agent import run_agent_city_crawl

        run_agent_city_crawl(city)
    else:
        from pipeline import run_city_pipeline

        run_city_pipeline(city)
    generate()


def run_province(province: str, run_id: str = "local") -> None:
    """Crawl all cities in a province using the LangGraph agent."""
    from agent import run_agent_city_crawl
    from crawl_tracker import record_province_crawl
    from provinces import PROVINCE_CITIES, get_cities_for_province

    canonical = next(
        (k for k in PROVINCE_CITIES if k.lower() == province.strip().lower()),
        None,
    )
    cities = get_cities_for_province(province)
    if not cities or canonical is None:
        print(f"Error: unknown province {province!r}", file=sys.stderr)
        sys.exit(1)

    init_db()
    before = get_stats()["total"]
    print(f"\n🏙️  Province crawl: {canonical} ({len(cities)} cities)\n")

    for city in cities:
        run_agent_city_crawl(city)

    after = get_stats()["total"]
    saved = after - before
    week = datetime.now().isocalendar()[1]
    record_province_crawl(canonical, saved, cities, week, run_id)

    print(f"\n[crawl] Province crawl complete: {canonical}")
    print(f"[crawl] New stores saved: {saved}")
    print(f"[crawl] Total in database: {after}")

    print_stats()
    generate()


def run_province_weekly() -> None:
    """
    Determine and crawl this week's province automatically.
    Stops when all provinces have been crawled at least once (one full cycle).
    """
    from crawl_tracker import get_crawl_coverage, was_crawled_this_week
    from provinces import PROVINCE_ROTATION, get_province_for_week

    week = datetime.now().isocalendar()[1]
    province = get_province_for_week(week)

    # ── One-cycle guard ────────────────────────────────────────────────────
    # If every province in PROVINCE_ROTATION has at least one crawl record,
    # the full cycle is complete. Stop here — do not crawl anything.
    coverage = get_crawl_coverage()
    never_crawled = [r for r in coverage if r.get("last_crawled_at") is None]

    if not never_crawled:
        init_db()
        total = get_stats()["total"]
        print("✅ Full rotation cycle complete — all provinces crawled at least once.")
        print(f"   Total stores in database: {total}")
        print("   To start a new cycle:")
        print("     python run.py --reset-cycle")
        print("   Or trigger a manual province crawl from GitHub Actions (mode=province).")
        # Write to crawl_output.txt so the email report reflects cycle completion
        with open("/tmp/crawl_output.txt", "w") as f:  # noqa: S108  # nosec B108
            f.write("Full rotation cycle complete — all 10 provinces crawled.\n")
            f.write(f"Total stores in database: {total}\n")
        return  # exit cleanly — workflow shows green, no crawl runs

    # ── Duplicate-run guard ────────────────────────────────────────────────
    if was_crawled_this_week(province):
        print(f"⚠️  {province} already crawled this week — skipping")
        return

    # ── Normal weekly crawl ────────────────────────────────────────────────
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    remaining = len(never_crawled)
    total_provinces = len(PROVINCE_ROTATION)
    print(f"🗓️  Week {week} → {province}")
    print(f"   Progress: {total_provinces - remaining + 1}/{total_provinces} provinces")
    print(f"   Remaining after this run: {remaining - 1}")
    run_province(province, run_id=run_id)


def reset_cycle() -> None:
    """
    Clear the crawl_history collection so the province rotation
    starts a fresh cycle from the beginning next weekly run.
    """
    try:
        from pymongo import MongoClient

        from config import MONGODB_DB_NAME, MONGODB_URI

        if not MONGODB_URI:
            print("Error: MONGODB_URI is not set.")
            return

        client = MongoClient(MONGODB_URI)
        result = client[MONGODB_DB_NAME]["crawl_history"].delete_many({})
        print(f"✅ Cycle reset — {result.deleted_count} crawl record(s) cleared")
        print("   The rotation will start from Ontario on the next weekly run.")
        print("   Or trigger a specific province manually: python run.py --province 'Ontario'")
    except Exception as e:
        print(f"Error resetting cycle: {e}")


def run_agent_test(store_names: list[str] | None, city: str) -> None:
    from agent import build_agent, run_agent_for_city, run_agent_for_store_names
    from config import llm_config_summary

    init_db()
    app = build_agent()

    if store_names:
        print(f"🤖 LangGraph agent — named stores in {city}")
        print(f"   LLM: {llm_config_summary()}\n")
        run_agent_for_store_names(app, store_names, city)
    else:
        print("🤖 LangGraph agent test: African grocery stores in Toronto")
        print(f"   LLM: {llm_config_summary()}\n")
        run_agent_for_city(app, city, "African grocery store")

    print_stats()
    generate()


def run_agent_full():
    from agent import run_full_crawl

    run_full_crawl()
    generate()


def generate():
    from generator import generate_site

    generate_site()


def print_stats():
    from storage import storage_summary

    init_db()
    stats = get_stats()
    print(f"\n── Database stats ({storage_summary()}) ──")
    print(f"Total stores: {stats['total']}")
    for row in stats["by_city"]:
        print(f"  {row['city']}: {row['count']} stores")
    for row in stats["by_category"]:
        print(f"  {row['category']}: {row['count']} stores")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    store_names = parse_store_names(args.names, args.names_file)

    if args.stats:
        print_stats()
    elif args.generate:
        generate()
    elif args.agent_full:
        run_agent_full()
    elif args.reset_cycle:
        reset_cycle()
    elif args.province_schedule:
        from provinces import print_schedule

        print_schedule()
    elif args.province_weekly:
        run_province_weekly()
    elif args.province:
        run_province(args.province)
    elif args.city_crawl:
        run_city_crawl(args.city, use_agent=args.agent)
    elif args.agent:
        run_agent_test(store_names or None, args.city)
    elif args.full:
        run_full()
    elif store_names:
        run_names_pipeline(store_names, args.city)
    else:
        run_test()


if __name__ == "__main__":
    main()
