#!/usr/bin/env python3
# run.py — CLI entry point
#
# Usage:
#   python run.py                   single city test (pipeline)
#   python run.py --full            full crawl (pipeline)
#   python run.py --agent           single city test (ReAct agent — for learning)
#   python run.py --generate        build HTML site from DB
#   python run.py --stats           print DB summary

import sys
from storage import init_db, get_stats


def run_test():
    from pipeline import run_test_pipeline
    run_test_pipeline()


def run_full():
    from pipeline import run_full_pipeline
    run_full_pipeline()
    generate()


def run_agent_test():
    """Keep the agent available for learning/experimentation."""
    from agent import build_agent, run_agent_for_city
    init_db()
    executor = build_agent()
    print("🤖 Agent test: African grocery stores in Toronto\n")
    result = run_agent_for_city(executor, "Toronto, Ontario", "African grocery store")
    print("\n── Agent final answer ──")
    print(result.get("output", ""))


def generate():
    from generator import generate_site
    generate_site()


def print_stats():
    init_db()
    stats = get_stats()
    print(f"\n── Database stats ──")
    print(f"Total stores: {stats['total']}")
    for row in stats["by_city"]:
        print(f"  {row['city']}: {row['count']} stores")
    for row in stats["by_category"]:
        print(f"  {row['category']}: {row['count']} stores")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--full" in args:
        run_full()
    elif "--agent" in args:
        run_agent_test()
    elif "--generate" in args:
        generate()
    elif "--stats" in args:
        print_stats()
    else:
        run_test()