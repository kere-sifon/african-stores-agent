#!/usr/bin/env python3
# run.py — CLI entry point
#
# Usage:
#   python run.py                   single city test (pipeline)
#   python run.py --full            full crawl (pipeline)
#   python run.py --agent           single city test (LangGraph agent)
#   python run.py --agent-full      full crawl (LangGraph agent)
#   python run.py --generate        build HTML site from DB
#   python run.py --stats           print DB summary

import sys

from storage import get_stats, init_db


def run_test():
    from pipeline import run_test_pipeline

    run_test_pipeline()


def run_full():
    from pipeline import run_full_pipeline

    run_full_pipeline()
    generate()


def run_agent_test():
    """LangGraph agent — single city test (Toronto, African grocery store)."""
    from agent import build_agent, run_agent_for_city
    from config import llm_config_summary

    init_db()
    print("🤖 LangGraph agent test: African grocery stores in Toronto")
    print(f"   LLM: {llm_config_summary()}\n")

    app = build_agent()
    run_agent_for_city(app, "Toronto, Ontario", "African grocery store")
    print_stats()


def run_agent_full():
    """LangGraph agent — full crawl across all cities and categories."""
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


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--full" in args:
        run_full()
    elif "--agent-full" in args:
        run_agent_full()
    elif "--agent" in args:
        run_agent_test()
    elif "--generate" in args:
        generate()
    elif "--stats" in args:
        print_stats()
    else:
        run_test()
