#!/usr/bin/env python3
# test_supervisor.py
# ─────────────────────────────────────────────────────────────────────────────
# Test runner for the multi-agent supervisor architecture.
# Runs against a DEV MongoDB database — never touches production data.
#
# USAGE:
#   # Set MONGODB_DB_NAME=african_stores_dev in .env.dev (see below)
#   python test_supervisor.py
#   python test_supervisor.py --city "Toronto, Ontario" --category "African grocery store"
#   python test_supervisor.py --smoke    # fast unit tests only (no LLM calls)
#
# DEV DATABASE SETUP:
#   Same Atlas cluster, different DB name.
#   Add to .env (or set env vars):
#     MONGODB_DB_NAME=african_stores_dev
#     LLM_PROVIDER=ollama   # use local Ollama to avoid Bedrock costs during dev
#
# TEST STAGES:
#   1. Smoke test — graph wires correctly, state types are valid
#   2. Unit test — supervisor routing logic with mock states
#   3. Integration test — single city run against dev DB with eval report
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("test_supervisor")


# ── Safety guard ───────────────────────────────────────────────────────────────


def _check_dev_db() -> None:
    """
    Hard stop if MONGODB_DB_NAME looks like the production database.
    We never run tests against african_stores (production).
    """
    db_name = os.getenv("MONGODB_DB_NAME", "african_stores")
    if db_name == "african_stores":
        print("\n❌  SAFETY STOP")
        print("   MONGODB_DB_NAME=african_stores looks like production.")
        print("   Set MONGODB_DB_NAME=african_stores_dev before running tests.")
        print("   Example: MONGODB_DB_NAME=african_stores_dev python test_supervisor.py\n")
        sys.exit(1)
    logger.info("Dev DB confirmed: MONGODB_DB_NAME=%s ✓", db_name)


# ── Stage 1: Smoke tests ───────────────────────────────────────────────────────


def test_graph_wiring() -> bool:
    """Verify the graph compiles without errors and all nodes are registered."""
    logger.info("── Stage 1: Graph wiring smoke test ──")
    try:
        from supervisor import build_supervisor_graph

        graph = build_supervisor_graph()
        compiled = graph.compile()

        # Check all expected nodes are present
        expected_nodes = {"supervisor", "search", "validate", "storage"}
        # LangGraph internal nodes: __start__, etc.
        actual_nodes = set(compiled.get_graph().nodes.keys())
        missing = expected_nodes - actual_nodes
        if missing:
            logger.error("Missing nodes: %s", missing)
            return False

        logger.info("✓ Graph compiled — nodes: %s", actual_nodes)
        return True
    except Exception as e:
        logger.error("✗ Graph wiring failed: %s", e)
        return False


def test_tool_boundaries() -> bool:
    """Verify each agent's tool set is correctly bounded."""
    logger.info("── Stage 1b: Tool boundary smoke test ──")
    try:
        from tools_search import get_search_tools
        from tools_storage import get_storage_tools
        from tools_validator import get_validator_tools

        search_tools = {t.name for t in get_search_tools()}
        validator_tools = {t.name for t in get_validator_tools()}
        storage_tools = {t.name for t in get_storage_tools()}

        assert "search_for_stores" in search_tools, "SearchAgent missing search_for_stores"
        assert "scrape_page" in search_tools, "SearchAgent missing scrape_page"
        assert "save_store_to_db" not in search_tools, "SearchAgent must NOT have save_store_to_db"
        assert "check_store_exists" not in search_tools, (
            "SearchAgent must NOT have check_store_exists"
        )

        assert "check_store_exists" in validator_tools, "ValidatorAgent missing check_store_exists"
        assert "save_store_to_db" not in validator_tools, (
            "ValidatorAgent must NOT have save_store_to_db"
        )
        assert "search_for_stores" not in validator_tools, (
            "ValidatorAgent must NOT have search_for_stores"
        )

        assert "save_store_to_db" in storage_tools, "StorageAgent missing save_store_to_db"
        assert "get_database_stats" in storage_tools, "StorageAgent missing get_database_stats"
        assert "search_for_stores" not in storage_tools, (
            "StorageAgent must NOT have search_for_stores"
        )
        assert "scrape_page" not in storage_tools, "StorageAgent must NOT have scrape_page"

        logger.info("✓ Tool boundaries correct")
        logger.info("  search=%s", search_tools)
        logger.info("  validator=%s", validator_tools)
        logger.info("  storage=%s", storage_tools)
        return True

    except AssertionError as e:
        logger.error("✗ Tool boundary violation: %s", e)
        return False
    except Exception as e:
        logger.error("✗ Tool boundary test failed: %s", e)
        return False


# ── Stage 2: Supervisor routing unit tests ─────────────────────────────────────


def test_supervisor_routing() -> bool:
    """
    Unit-test the supervisor routing logic with mock states.
    No LLM calls — pure state machine testing.
    """
    logger.info("── Stage 2: Supervisor routing unit tests ──")
    from supervisor import supervisor_node

    cases = [
        {
            "name": "empty state → search",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": [],
                "validated_stores": [],
                "saved_count": 0,
                "errors": [],
                "messages": [],
                "next": "",
                "validator_attempted": False,
            },
            "expected": "search",
        },
        {
            "name": "has search results → validate",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": ["some scraped text with a store"],
                "validated_stores": [],
                "saved_count": 0,
                "errors": [],
                "messages": [],
                "next": "",
                "validator_attempted": False,
            },
            "expected": "validate",
        },
        {
            "name": "has validated stores → storage",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": ["some text"],
                "validated_stores": ['{"name": "Lagos Market", "city": "Toronto"}'],
                "saved_count": 0,
                "errors": [],
                "messages": [],
                "next": "",
                "validator_attempted": True,
            },
            "expected": "storage",
        },
        {
            "name": "saved_count > 0 → END",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": ["some text"],
                "validated_stores": ['{"name": "Lagos Market", "city": "Toronto"}'],
                "saved_count": 2,
                "errors": [],
                "messages": [],
                "next": "",
                "validator_attempted": True,
            },
            "expected": "END",
        },
        {
            # search_results empty + errors = infra failure (e.g. bad AWS creds)
            # supervisor must abort to END, not retry search forever
            "name": "empty search + errors → END (infra failure)",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": [],
                "validated_stores": [],
                "saved_count": 0,
                "errors": [
                    "SearchAgent error: UnrecognizedClientException — security token invalid"
                ],
                "messages": [],
                "next": "",
                "validator_attempted": False,
            },
            "expected": "END",
        },
        {
            # search ran and returned content, but errors indicate nothing usable
            # (e.g. all scrapes failed) — supervisor should dead-end rather than
            # sending noise to the Validator.
            "name": "search content + errors → END (dead end)",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": ["HTTP error scraping url: 403", "Error scraping url: timeout"],
                "validated_stores": [],
                "saved_count": 0,
                "errors": ["SearchAgent error: all scrapes failed"],
                "messages": [],
                "next": "",
                "validator_attempted": False,
            },
            "expected": "END",
        },
        {
            # validator ran but found nothing → must END, not loop back to validate
            "name": "validator ran, found nothing → END (no valid stores)",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": ["some scraped text"],
                "validated_stores": [],
                "saved_count": 0,
                "errors": [],
                "messages": [],
                "next": "",
                "validator_attempted": True,
            },
            "expected": "END",
        },
        {
            # Regression test: storage already ran once but saved_count stayed
            # at 0 (all duplicates, or save calls silently failed against a
            # weak local LLM's tool-calling). Without storage_attempted, the
            # supervisor would route back to "storage" forever until
            # recursion_limit=25 — this must END instead, accepting the
            # outcome after one attempt, same as the validator pattern.
            "name": "storage ran, saved nothing → END (not infinite retry)",
            "state": {
                "city": "Toronto",
                "category": "grocery",
                "search_results": ["some text"],
                "validated_stores": ['{"name": "Lagos Market", "city": "Toronto"}'],
                "saved_count": 0,
                "errors": [],
                "messages": [],
                "next": "",
                "validator_attempted": True,
                "storage_attempted": True,
            },
            "expected": "END",
        },
    ]

    all_passed = True
    for case in cases:
        result = supervisor_node(case["state"])
        actual = result.get("next")
        passed = actual == case["expected"]
        status = "✓" if passed else "✗"
        logger.info("%s %s → got=%s expected=%s", status, case["name"], actual, case["expected"])
        if not passed:
            all_passed = False

    return all_passed


# ── Stage 3: Integration test ──────────────────────────────────────────────────


def test_integration(city: str, category: str) -> bool:
    """
    Run one full supervisor pipeline against the dev database.
    Prints per-agent eval report at the end.
    """
    _check_dev_db()

    logger.info("── Stage 3: Integration test ──")
    logger.info("city=%s | category=%s | db=%s", city, category, os.getenv("MONGODB_DB_NAME"))

    from eval_agents import evaluate_run, print_eval_report
    from storage import init_db
    from supervisor import build_supervisor_agent, run_supervisor_for_city

    init_db()
    app = build_supervisor_agent(use_checkpointing=True)
    result = run_supervisor_for_city(app, city, category)

    scores = evaluate_run(result)
    print_eval_report(scores)

    # Pass/fail threshold: at least the pipeline should complete without crashing
    success = result.get("saved_count", 0) >= 0  # even 0 is OK — city may be exhausted
    errors = result.get("errors", [])

    if errors:
        logger.warning("Pipeline completed with %d errors:", len(errors))
        for err in errors:
            logger.warning("  %s", err)

    return success


# ── Stage 4: Eval unit tests ───────────────────────────────────────────────────


def test_eval_module() -> bool:
    """Unit-test the eval module with synthetic data."""
    import json

    logger.info("── Stage 4: Eval module unit tests ──")
    try:
        from eval_agents import (
            evaluate_search_precision,
            evaluate_storage_dedup,
            evaluate_validator_accuracy,
        )

        # Search precision: 2 of 3 chunks have store signals
        results = [
            "Lagos Market 555-0100 located at 100 Rexdale Blvd Toronto ON African Grocery Store",
            "Wikipedia article about African cuisine no business info",
            "Naija Foods Restaurant 555-0101 at 45 Jane St Scarborough ON",
        ]
        sp = evaluate_search_precision(results)
        if sp["signal_chunks"] < 1:
            logger.error("Expected signal chunks, got %s", sp)
            return False
        logger.info("✓ search_precision=%s", sp["score"])

        # Validator accuracy: 2 valid, 1 missing contact
        validated = [
            json.dumps(
                {
                    "name": "Lagos Market",
                    "city": "Toronto",
                    "phone": "555-0100",
                    "category": "Grocery",
                }
            ),
            json.dumps(
                {
                    "name": "Naija Foods",
                    "city": "Toronto",
                    "address": "45 Jane St",
                    "category": "Restaurant",
                }
            ),
            json.dumps({"name": "Unknown Store", "city": "Toronto"}),
        ]
        va = evaluate_validator_accuracy(validated)
        if va["valid"] != 2:
            logger.error("Expected 2 valid, got %s", va["valid"])
            return False
        if va["invalid"] != 1:
            logger.error("Expected 1 invalid, got %s", va["invalid"])
            return False
        logger.info("✓ validator_accuracy=%s", va["score"])

        # Storage dedup: 2 new inserts, 1 dup
        save_log = [
            "Saved: Lagos Market (Toronto)",
            "Saved: Naija Foods (Toronto)",
            "Already in database: Old Store (Toronto)",
        ]
        sd = evaluate_storage_dedup(save_log)
        if sd["new_inserts"] != 2:
            logger.error("Expected 2 new inserts, got %s", sd["new_inserts"])
            return False
        if sd["duplicates"] != 1:
            logger.error("Expected 1 dup, got %s", sd["duplicates"])
            return False
        logger.info("✓ storage_dedup_rate=%s", sd["score"])

        return True
    except Exception as e:
        logger.error("✗ Eval module test failed: %s", e)
        return False


# ── Stage 5: Confidence extraction (HITL escalation) unit tests ────────────────


def test_confidence_extraction() -> bool:
    """
    Unit-test _extract_json_blocks's confidence-based routing.
    No LLM calls — pure parsing logic, testing the HITL escalation split
    between validated_stores (high confidence) and pending_review (low
    confidence / missing confidence field).
    """
    logger.info("── Stage 5: Confidence extraction unit tests ──")
    from supervisor import _extract_json_blocks

    all_passed = True

    # Case 1: high confidence → validated, not flagged for review
    content = (
        '```json\n{"name": "Test Store A", "city": "Toronto", "address": "1 St", '
        '"confidence": "high"}\n```'
    )
    validated, review = _extract_json_blocks(content, "Toronto", logger)
    passed = len(validated) == 1 and len(review) == 0
    logger.info("%s high confidence → validated, not flagged", "✓" if passed else "✗")
    all_passed = all_passed and passed

    # Case 2: low confidence → flagged for review, not validated
    content = '```json\n{"name": "Test Store B", "city": "Toronto", "confidence": "low"}\n```'
    validated, review = _extract_json_blocks(content, "Toronto", logger)
    passed = len(validated) == 0 and len(review) == 1
    logger.info("%s low confidence → flagged, not validated", "✓" if passed else "✗")
    all_passed = all_passed and passed

    # Case 3: missing confidence field → defaults to low (fail toward review,
    # not toward silent auto-acceptance)
    content = '```json\n{"name": "Test Store C", "city": "Toronto", "address": "2 St"}\n```'
    validated, review = _extract_json_blocks(content, "Toronto", logger)
    passed = len(validated) == 0 and len(review) == 1
    logger.info("%s missing confidence field → defaults to flagged", "✓" if passed else "✗")
    all_passed = all_passed and passed

    # Case 4: mixed batch — confidence is evaluated per-store, not globally
    content = (
        '```json\n{"name": "D", "city": "Toronto", "address": "1", "confidence": "high"}\n```\n'
        '```json\n{"name": "E", "city": "Toronto", "confidence": "low"}\n```'
    )
    validated, review = _extract_json_blocks(content, "Toronto", logger)
    passed = len(validated) == 1 and len(review) == 1
    logger.info("%s mixed batch → split correctly per-store", "✓" if passed else "✗")
    all_passed = all_passed and passed

    return all_passed


# ── CLI entrypoint ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Test the multi-agent supervisor")
    parser.add_argument("--city", default="Toronto, Ontario", help="City to crawl")
    parser.add_argument("--category", default="African grocery store", help="Store category")
    parser.add_argument("--smoke", action="store_true", help="Smoke + unit tests only (no LLM)")
    args = parser.parse_args()

    results: dict[str, bool] = {}

    # Always run smoke + unit tests
    results["graph_wiring"] = test_graph_wiring()
    results["tool_boundaries"] = test_tool_boundaries()
    results["supervisor_routing"] = test_supervisor_routing()
    results["eval_module"] = test_eval_module()
    results["confidence_extraction"] = test_confidence_extraction()

    if not args.smoke:
        results["integration"] = test_integration(args.city, args.category)

    print("\n" + "=" * 50)
    print("  TEST RESULTS")
    print("=" * 50)
    all_passed = True
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False
    print("=" * 50)

    if all_passed:
        print("\n✅  All tests passed.")
    else:
        print("\n❌  Some tests failed — see logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
