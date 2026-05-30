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
#   python run.py --generate        build HTML site from DB
#   python run.py --stats           print DB summary

from __future__ import annotations

import argparse
import re
import sys
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
