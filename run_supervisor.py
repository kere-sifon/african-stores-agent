#!/usr/bin/env python3
# run_supervisor.py
# ─────────────────────────────────────────────────────────────────────────────
# Production entrypoint for the multi-agent supervisor pipeline.
# Drop-in replacement for run.py when using the supervisor architecture.
#
# USAGE:
#   python run_supervisor.py --city "Toronto, Ontario"
#   python run_supervisor.py --city "Toronto, Ontario" --category "African restaurant"
#   python run_supervisor.py --all    # all TARGET_CITIES × SEARCH_QUERIES
#   python run_supervisor.py --eval   # print per-agent eval report after each run
#
# ENVIRONMENT:
#   Same .env as the single-agent pipeline. The supervisor reads from:
#     MONGODB_DB_NAME  — target database (african_stores for production)
#     LLM_PROVIDER     — bedrock or ollama
#     MONGODB_URI      — Atlas connection string
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import logging

from config import SEARCH_QUERIES, TARGET_CITIES
from eval_agents import evaluate_run, print_eval_report
from storage import init_db
from supervisor import build_supervisor_agent, run_supervisor_for_city

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("run_supervisor")


def main():
    parser = argparse.ArgumentParser(description="Run the multi-agent supervisor pipeline")
    parser.add_argument("--city", help="Single city to crawl (e.g. 'Toronto, Ontario')")
    parser.add_argument("--category", default=None, help="Store category (default: all)")
    parser.add_argument("--all", action="store_true", help="Run all cities × all categories")
    parser.add_argument("--eval", action="store_true", help="Print per-agent eval report")
    args = parser.parse_args()

    init_db()
    app = build_supervisor_agent(use_checkpointing=True)

    categories = [args.category] if args.category else SEARCH_QUERIES
    cities = TARGET_CITIES if args.all else ([args.city] if args.city else [TARGET_CITIES[0]])

    total = len(cities) * len(categories)
    completed = 0

    for city in cities:
        for category in categories:
            completed += 1
            logger.info("[%d/%d] city=%s | category=%s", completed, total, city, category)
            try:
                result = run_supervisor_for_city(app, city, category)
                if args.eval:
                    scores = evaluate_run(result)
                    print_eval_report(scores)
            except Exception as e:
                logger.error("Run failed for (%s, %s): %s — continuing", city, category, e)

    logger.info("✅ Supervisor pipeline complete.")


if __name__ == "__main__":
    main()
