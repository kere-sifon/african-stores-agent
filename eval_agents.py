# eval_agents.py
# ─────────────────────────────────────────────────────────────────────────────
# Per-agent evaluation scores for the multi-agent supervisor pipeline.
#
# WHY PER-AGENT EVALS?
#   End-to-end accuracy hides which agent failed. If 3 stores are saved but
#   15 were found, the problem could be Validator over-rejection OR Storage
#   errors — you can't tell without per-agent metrics.
#
# THREE METRICS:
#   search_precision   — % of search_results chunks that contained at least
#                        one extractable store candidate (signal vs noise)
#   validator_accuracy — % of validated_stores that passed MongoDB write
#                        without error (no malformed JSON, no schema errors)
#   storage_dedup_rate — % of save attempts that were true new inserts
#                        (not "Already in database" returns) — measures
#                        how well the deduplication pipeline is working.
#                        Target: low dedup rate = Validator is doing its job.
#
# USAGE:
#   from eval_agents import evaluate_run, print_eval_report
#   scores = evaluate_run(result_state, save_log)
#   print_eval_report(scores)
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("eval")


def evaluate_search_precision(search_results: list[str]) -> dict:
    """
    Search precision: what fraction of scraped chunks contained extractable store data?

    Heuristic: a chunk "has a store" if it contains at least two of:
      - a business name pattern (Title Case word sequence)
      - a phone number pattern (digits with separators)
      - an address pattern (number + street word)
      - a city name from known TARGET_CITIES

    This is intentionally lightweight — a full NER pass would be overkill here.
    """
    from config import TARGET_CITIES

    city_names = {c.split(",")[0].strip().lower() for c in TARGET_CITIES}

    phone_re = re.compile(r"\b\d{3}[\s\-\.]\d{3}[\s\-\.]\d{4}\b")
    address_re = re.compile(r"\b\d{1,5}\s+[A-Z][a-z]+\s+(St|Ave|Rd|Blvd|Dr|Way|Pl|Ct)\b")
    title_re = re.compile(r"\b([A-Z][a-z]+ ){2,4}(Store|Market|Restaurant|Grocery|Bakery|Salon)\b")

    total = len(search_results)
    if total == 0:
        return {"score": 0.0, "total_chunks": 0, "signal_chunks": 0}

    signal = 0
    for chunk in search_results:
        signals = 0
        if phone_re.search(chunk):
            signals += 1
        if address_re.search(chunk):
            signals += 1
        if title_re.search(chunk):
            signals += 1
        if any(city in chunk.lower() for city in city_names):
            signals += 1
        if signals >= 2:
            signal += 1

    score = round(signal / total, 3)
    logger.info("SearchPrecision: %d/%d chunks with signal → score=%.3f", signal, total, score)
    return {"score": score, "total_chunks": total, "signal_chunks": signal}


def evaluate_validator_accuracy(validated_stores: list[str]) -> dict:
    """
    Validator accuracy: what fraction of validated_stores are schema-valid JSON
    with the minimum required fields (name + city + one contact field)?

    This catches cases where the Validator emits malformed JSON or incomplete
    store objects that will fail at the Storage Agent.
    """
    total = len(validated_stores)
    if total == 0:
        return {"score": 0.0, "total": 0, "valid": 0, "invalid": 0}

    valid_count = 0
    invalid_details: list[str] = []

    for raw in validated_stores:
        try:
            obj = json.loads(raw)
            has_name = bool(obj.get("name"))
            has_city = bool(obj.get("city"))
            has_contact = any(obj.get(f) for f in ("address", "phone", "website"))

            if has_name and has_city and has_contact:
                valid_count += 1
            else:
                missing = []
                if not has_name:
                    missing.append("name")
                if not has_city:
                    missing.append("city")
                if not has_contact:
                    missing.append("contact(address/phone/website)")
                invalid_details.append(f"missing: {', '.join(missing)}")

        except json.JSONDecodeError as e:
            invalid_details.append(f"invalid JSON: {e}")

    score = round(valid_count / total, 3)
    logger.info(
        "ValidatorAccuracy: %d/%d schema-valid → score=%.3f | issues=%s",
        valid_count,
        total,
        score,
        invalid_details or "none",
    )
    return {
        "score": score,
        "total": total,
        "valid": valid_count,
        "invalid": total - valid_count,
        "issues": invalid_details,
    }


def evaluate_storage_dedup(save_log: list[str]) -> dict:
    """
    Storage dedup rate: what fraction of save attempts were true new inserts?

    save_log is a list of return strings from save_store_to_db tool calls:
      "Saved: Store Name (City)"           → new insert
      "Already in database: ..."           → duplicate caught
      "Skipped: needs address..."          → quality gate (not a dedup issue)
      "Error ..."                          → storage failure

    A low dedup rate (close to 1.0) means the Validator is working well.
    A high dedup rate means many duplicates are reaching Storage — the
    Validator's check_store_exists calls may be failing.
    """
    total = len(save_log)
    if total == 0:
        return {"score": 1.0, "total": 0, "new_inserts": 0, "duplicates": 0, "errors": 0}

    new_inserts = sum(1 for s in save_log if s.startswith("Saved:"))
    duplicates = sum(1 for s in save_log if "Already in database" in s)
    errors = sum(1 for s in save_log if s.startswith("Error") or s.startswith("DB error"))
    skipped = total - new_inserts - duplicates - errors

    # Score = fraction of attempts that were genuine new inserts
    # (excludes errors from denominator — errors are a separate concern)
    effective_total = total - errors
    score = round(new_inserts / effective_total, 3) if effective_total > 0 else 0.0

    logger.info(
        "StorageDedupRate: new=%d dup=%d skip=%d err=%d → score=%.3f",
        new_inserts,
        duplicates,
        skipped,
        errors,
        score,
    )
    return {
        "score": score,
        "total": total,
        "new_inserts": new_inserts,
        "duplicates": duplicates,
        "skipped": skipped,
        "errors": errors,
    }


def evaluate_run(result_state: dict, save_log: list[str] | None = None) -> dict:
    """
    Run all three per-agent evaluations against a completed supervisor run.

    Args:
        result_state: the dict returned by app.invoke()
        save_log: list of save_store_to_db return strings (optional;
                  extracted from result_state messages if not provided)

    Returns:
        dict with keys: search, validator, storage, summary
    """
    search_results = result_state.get("search_results", [])
    validated_stores = result_state.get("validated_stores", [])

    # Auto-extract save log from message history if not explicitly provided
    if save_log is None:
        save_log = _extract_save_log(result_state.get("messages", []))

    search_eval = evaluate_search_precision(search_results)
    validator_eval = evaluate_validator_accuracy(validated_stores)
    storage_eval = evaluate_storage_dedup(save_log)

    return {
        "search": search_eval,
        "validator": validator_eval,
        "storage": storage_eval,
        "summary": {
            "search_precision": search_eval["score"],
            "validator_accuracy": validator_eval["score"],
            "storage_new_insert_rate": storage_eval["score"],
            "total_saved": result_state.get("saved_count", 0),
            "total_errors": len(result_state.get("errors", [])),
        },
    }


def print_eval_report(scores: dict) -> None:
    """Human-readable evaluation report for logs and interview demos."""
    s = scores.get("summary", {})
    print("\n" + "=" * 55)
    print("  PER-AGENT EVALUATION REPORT")
    print("=" * 55)
    print(f"  Search Precision          {s.get('search_precision', 0):.3f}")
    print("    (signal chunks / total scraped chunks)")

    print(f"\n  Validator Accuracy        {s.get('validator_accuracy', 0):.3f}")
    v = scores.get("validator", {})
    print(f"    ({v.get('valid', 0)}/{v.get('total', 0)} schema-valid store objects)")
    if v.get("issues"):
        for issue in v["issues"][:3]:
            print(f"    ⚠ {issue}")

    print(f"\n  Storage New-Insert Rate   {s.get('storage_new_insert_rate', 0):.3f}")
    st = scores.get("storage", {})
    print(
        f"    new={st.get('new_inserts', 0)}  dup={st.get('duplicates', 0)}  "
        f"skip={st.get('skipped', 0)}  err={st.get('errors', 0)}"
    )

    print(f"\n  Total Saved This Run      {s.get('total_saved', 0)}")
    print(f"  Pipeline Errors           {s.get('total_errors', 0)}")
    print("=" * 55)


# ── Internal helpers ───────────────────────────────────────────────────────────


def _extract_save_log(messages: list) -> list[str]:
    """
    Extract save_store_to_db return strings from message history.
    Tool result messages from the Storage Agent contain these strings.
    """
    save_log: list[str] = []
    save_keywords = ("Saved:", "Already in database", "Skipped:", "Error", "DB error")

    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            content = str(msg.content)
            if any(kw in content for kw in save_keywords):
                # Each line may be a separate save result
                for line in content.splitlines():
                    line = line.strip()
                    if any(line.startswith(kw) for kw in save_keywords):
                        save_log.append(line)

    return save_log
