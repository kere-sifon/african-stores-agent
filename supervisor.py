# supervisor.py
# ─────────────────────────────────────────────────────────────────────────────
# Multi-agent supervisor architecture for African Stores Canada.
#
# ARCHITECTURE:
#   Supervisor owns all routing decisions.
#   Three specialist agents, each with a bounded tool set:
#     - SearchAgent   → search_for_stores, scrape_page
#     - ValidatorAgent → check_store_exists, quality gate (no DB writes)
#     - StorageAgent  → save_store_to_db, get_database_stats
#
# FLOW:
#   START → supervisor → search_agent → supervisor
#                      → validator_agent → supervisor
#                      → storage_agent → supervisor
#                      → END
#
#   Specialists ALWAYS return to supervisor. Supervisor owns routing.
#   recursion_limit=25 prevents infinite loops at compile time.
#
# STATE HANDOFFS:
#   search_results      — raw search + scrape text from SearchAgent
#   validated_stores    — JSON strings ready for storage from ValidatorAgent
#   saved_count         — running tally updated by StorageAgent
#   errors              — non-fatal errors accumulated across all agents
#   next                — supervisor's routing decision ("search"/"validate"/"storage"/"END")
#
# LOGGING:
#   Every supervisor routing decision is logged with the state snapshot it
#   received. This is the primary debuggability mechanism — without it,
#   failures in multi-agent graphs are nearly impossible to trace.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from config import LLM_PROVIDER, MONGODB_URI, get_llm
from cost_tracking import extract_usage
from tools_search import get_search_tools
from tools_storage import get_storage_tools
from tools_validator import get_validator_tools

# ── Logging setup ──────────────────────────────────────────────────────────────
# Structured log lines make it trivial to grep for supervisor decisions
# or individual agent completions in CI logs.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("supervisor")
search_logger = logging.getLogger("search_agent")
validator_logger = logging.getLogger("validator_agent")
storage_logger = logging.getLogger("storage_agent")


# ── Typed state ────────────────────────────────────────────────────────────────
# Clean handoff contract between supervisor and all specialist agents.
# Annotated[list, operator.add] — new items are appended, never replaced.
# This means agents accumulate results safely without overwriting each other.


class AgentState(TypedDict):
    # Task context (set once at entry, read-only for specialists)
    city: str
    category: str
    # category holds EITHER a store category ("African grocery store") used
    # for an open crawl, OR a specific store name ("Ashanti African Market")
    # when searching for one named store. is_named_store disambiguates which
    # mode this run is in, since the two need different search phrasing.
    is_named_store: bool

    # Handoff channels (each specialist appends to its output channel)
    messages: Annotated[list[BaseMessage], operator.add]
    search_results: Annotated[list[str], operator.add]  # raw text from SearchAgent
    validated_stores: Annotated[list[str], operator.add]  # JSON strings from ValidatorAgent
    errors: Annotated[list[str], operator.add]  # non-fatal errors from any agent
    save_log: Annotated[list[str], operator.add]  # raw save_store_to_db return strings
    # from StorageAgent only — used by eval_agents.evaluate_storage_dedup instead
    # of reconstructing from shared `messages`, which mixes all three agents'
    # output and over-counts (see eval_agents._extract_save_log docstring)
    usage_log: Annotated[list[dict], operator.add]  # CallUsage.__dict__ entries
    # from every LLM invocation across all three specialist agents — see
    # cost_tracking.py. Each agent node appends one dict per LLM call it makes.

    # Mutable counters (supervisor updates these)
    saved_count: int
    validator_attempted: bool  # True after ValidatorAgent has run once — prevents re-validate loop
    storage_attempted: bool  # True after StorageAgent has run once — prevents re-storage loop
    # when validated stores are all duplicates / saves silently fail (e.g. weak
    # local LLM tool-calling)

    # Routing signal — supervisor writes, graph reads
    next: str


# ── Supervisor prompts ─────────────────────────────────────────────────────────

SUPERVISOR_SYSTEM = """You are the orchestration supervisor for the African Stores Canada
cataloguing system.

You receive a task (find African stores in a city) and route it through
three specialist agents in sequence:
1. search  — finds stores via web search and scraping
2. validate — checks each result against quality criteria and deduplication
3. storage — saves validated stores to MongoDB

Your routing decisions:
- If search_results is empty → route to "search"
- If search_results has data but validated_stores is empty → route to "validate"
- If validated_stores has stores ready to save → route to "storage"
- If storage has completed (saved_count > 0 or validated_stores is exhausted) → route to "END"
- If search returned nothing and retries are exhausted → route to "END"

Respond ONLY with one of: search | validate | storage | END
"""

SEARCH_SYSTEM = """You are the Search Agent for African Stores Canada.

Your ONLY job: find African stores in the given city.
Tools available: search_for_stores, scrape_page

Steps:
1. Call search_for_stores with a query like "African grocery store {city} Canada"
2. For each promising URL in the results, call scrape_page to get full details
3. Stop after searching once and scraping up to 5 URLs

Return ALL raw text you gathered — the Validator Agent will assess quality.
Do NOT make any judgments about quality. Do NOT save anything.
"""

VALIDATOR_SYSTEM = """You are the Validator Agent for African Stores Canada.

Your ONLY job: evaluate search_results text and extract valid African stores.
Tools available: check_store_exists

For each candidate store you identify in the search_results:
1. Call check_store_exists("Store Name, City") to avoid duplicates
2. If NOT FOUND: output a JSON object with fields:
   name, category, city, province, address, phone, website, description,
   source_url, confidence
3. If EXISTS: skip it

The "confidence" field must be either "high" or "low":
- "high": name, city, and at least one contact field (address/phone/website)
  are all DIRECTLY STATED in the source text — you did not have to guess
  or infer any of them.
- "low": you had to infer or guess at any field — e.g. the city wasn't
  explicitly stated and you inferred it from context, the phone number
  format was ambiguous, or the source text was unclear about whether this
  is the exact business being searched for vs. a similarly-named one.
  When in doubt, use "low" rather than "high" — a human will review it.

Output each valid store as a separate JSON string on its own line.
Do NOT save anything to the database. Do NOT scrape new URLs.
Quality threshold: store must have name + city + at least one of (address, phone, website).
"""

STORAGE_SYSTEM = """You are the Storage Agent for African Stores Canada.

Your ONLY job: save pre-validated stores to MongoDB.
Tools available: save_store_to_db, get_database_stats

For each store in validated_stores:
1. Call save_store_to_db with the JSON string
2. Log the result

Call get_database_stats once at the end to confirm totals.
Do NOT search for new stores. Do NOT modify any store data.
"""


# ── Supervisor node ────────────────────────────────────────────────────────────


def supervisor_node(state: AgentState) -> dict:
    """
    The orchestration brain. Reads state, decides which specialist runs next.

    Logging here is the primary debuggability mechanism. Every routing decision
    is logged with the full state snapshot — this is what makes failures
    traceable in a multi-agent graph.
    """
    city = state.get("city", "unknown")
    search_results = state.get("search_results", [])
    validated_stores = state.get("validated_stores", [])
    saved_count = state.get("saved_count", 0)
    errors = state.get("errors", [])
    validator_attempted = state.get("validator_attempted", False)
    storage_attempted = state.get("storage_attempted", False)

    # ── Log the full state snapshot received ──────────────────────────────────
    logger.info(
        "SUPERVISOR ROUTING | city=%s | search_results=%d | validated_stores=%d | "
        "saved_count=%d | errors=%d | validator_attempted=%s | storage_attempted=%s",
        city,
        len(search_results),
        len(validated_stores),
        saved_count,
        len(errors),
        validator_attempted,
        storage_attempted,
    )

    # ── Routing logic ─────────────────────────────────────────────────────────
    # Rule 1: No search results yet → run search.
    # Exception: if errors already exist with empty results, the SearchAgent
    # has already failed (e.g. invalid AWS credentials, network error).
    # Retrying will loop until the recursion limit — abort to END immediately.
    if not search_results and not errors:
        decision = "search"
        logger.info("SUPERVISOR DECISION → %s (reason: search_results empty)", decision)

    elif not search_results and errors:
        decision = "END"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: search_results empty after errors=%s"
            " — infra failure, aborting)",
            decision,
            errors,
        )

    # Rule 2: Have search results, validator not yet attempted → run validator
    elif search_results and not validated_stores and not validator_attempted and not errors:
        decision = "validate"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: %d search results awaiting validation)",
            decision,
            len(search_results),
        )

    # Rule 2b: Validator already ran but found nothing valid → END (no stores in this city/category)
    elif search_results and not validated_stores and validator_attempted:
        decision = "END"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: validator ran but found no valid stores"
            " — city/category exhausted)",
            decision,
        )

    # Rule 2c: Search returned content but errors indicate nothing usable → dead end
    elif search_results and not validated_stores and errors:
        decision = "END"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: search produced results but errors=%s — dead end)",
            decision,
            errors,
        )

    # Rule 3: Have validated stores, storage not yet attempted → run storage
    elif validated_stores and saved_count == 0 and not storage_attempted:
        decision = "storage"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: %d validated stores ready to save)",
            decision,
            len(validated_stores),
        )

    # Rule 3b: Storage already ran once but saved nothing new (all duplicates,
    # or save calls silently failed) → END rather than retrying forever.
    # This mirrors Rule 2b for the validator — one attempt per specialist,
    # then accept the outcome.
    elif validated_stores and saved_count == 0 and storage_attempted:
        decision = "END"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: storage ran but saved 0 new stores"
            " — likely all duplicates or save failures — accepting outcome)",
            decision,
        )

    # Rule 4: Storage completed with saves → done
    elif saved_count > 0:
        decision = "END"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: saved_count=%d, pipeline complete)",
            decision,
            saved_count,
        )

    # Rule 5: Dead end — search returned nothing, no stores found
    else:
        decision = "END"
        logger.info(
            "SUPERVISOR DECISION → %s (reason: no viable path forward, errors=%s)",
            decision,
            errors,
        )

    return {"next": decision}


# ── Specialist agent nodes ─────────────────────────────────────────────────────


def search_agent_node(state: AgentState) -> dict:
    """
    Search Agent — bounded to search_for_stores and scrape_page only.
    Returns raw text appended to search_results.
    Errors are non-fatal: logged and appended to errors list.
    """
    city = state.get("city", "")
    category = state.get("category", "African store")
    is_named_store = state.get("is_named_store", False)

    search_logger.info(
        "SearchAgent START | city=%s | category=%s | is_named_store=%s",
        city,
        category,
        is_named_store,
    )

    llm = get_llm()
    tools = get_search_tools()
    llm_with_tools = llm.bind_tools(tools)

    if is_named_store:
        # category holds a specific store name here, not a category — search
        # for that exact business, not a class of businesses. Pluralizing or
        # generalizing a proper noun ("Ashanti African Markets") produces a
        # nonsensical query, so this branch is phrased completely differently
        # from the category-crawl branch below.
        task_text = (
            f'Find the specific store "{category}" in {city}, Canada. '
            f"Search for this exact business by name, then scrape up to 5 "
            f"promising URLs (its website, directory listings, reviews) for "
            f"its address, phone, and other contact details."
        )
    else:
        task_text = (
            f"Find {category}s in {city}, Canada. "
            f"Search once, then scrape up to 5 promising URLs for store details."
        )

    messages = [
        SystemMessage(content=SEARCH_SYSTEM),
        HumanMessage(content=task_text),
    ]

    # Run the search agent loop (search → scrape → done)
    tool_node = ToolNode(tools)
    new_results: list[str] = []
    new_errors: list[str] = []
    new_usage: list[dict] = []

    try:
        # Single reasoning step — agent decides searches + scrapes
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        new_usage.append(
            extract_usage(
                response, agent="search", call_type="reasoning", provider=LLM_PROVIDER
            ).__dict__
        )

        # Execute any tool calls
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_results = tool_node.invoke({"messages": messages})
            tool_messages = tool_results.get("messages", [])
            messages.extend(tool_messages)

            # Collect all tool output text into search_results
            for msg in tool_messages:
                if hasattr(msg, "content") and msg.content:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    new_results.append(content)
                    search_logger.debug("SearchAgent collected %d chars", len(content))

            # Second reasoning step — agent may want to scrape more
            response2 = llm_with_tools.invoke(messages)
            messages.append(response2)
            new_usage.append(
                extract_usage(
                    response2, agent="search", call_type="followup", provider=LLM_PROVIDER
                ).__dict__
            )

            if hasattr(response2, "tool_calls") and response2.tool_calls:
                tool_results2 = tool_node.invoke({"messages": messages})
                for msg in tool_results2.get("messages", []):
                    if hasattr(msg, "content") and msg.content:
                        content = msg.content if isinstance(msg.content, str) else str(msg.content)
                        new_results.append(content)

    except Exception as e:
        err_msg = f"SearchAgent error: {e}"
        search_logger.error(err_msg)
        new_errors.append(err_msg)

    search_logger.info(
        "SearchAgent DONE | collected=%d result chunks | errors=%d",
        len(new_results),
        len(new_errors),
    )

    state_update: dict = {"next": "supervisor", "messages": messages}
    if new_results:
        state_update["search_results"] = new_results
    if new_errors:
        state_update["errors"] = new_errors
    if new_usage:
        state_update["usage_log"] = new_usage

    return state_update


def validator_agent_node(state: AgentState) -> dict:
    """
    Validator Agent — bounded to check_store_exists only.
    Reads search_results, emits validated JSON strings to validated_stores.
    Never writes to the main stores database.

    Low-confidence candidates (per the "confidence" field the Validator is
    instructed to emit — see VALIDATOR_SYSTEM) are written directly to the
    pending_review queue instead of validated_stores, for human review via
    the ops dashboard rather than being silently dropped or auto-accepted.
    This write happens here rather than being threaded through AgentState
    because pending_review entries don't need supervisor routing or
    storage-agent involvement — they're a side channel, not part of the
    main accept/save pipeline.
    """
    search_results = state.get("search_results", [])
    city = state.get("city", "")
    category = state.get("category", "")

    validator_logger.info(
        "ValidatorAgent START | city=%s | evaluating %d result chunks",
        city,
        len(search_results),
    )

    llm = get_llm()
    tools = get_validator_tools()
    llm_with_tools = llm.bind_tools(tools)

    combined_text = "\n\n---\n\n".join(search_results)

    messages = [
        SystemMessage(content=VALIDATOR_SYSTEM),
        HumanMessage(
            content=(
                f"Evaluate these search results for African stores in {city}, Canada.\n\n"
                f"For each candidate store, check if it exists, then output valid ones as JSON.\n\n"
                f"SEARCH RESULTS:\n{combined_text}"
            )
        ),
    ]

    tool_node = ToolNode(tools)
    new_validated: list[str] = []
    new_errors: list[str] = []
    new_usage: list[dict] = []
    needs_review: list[dict] = []

    try:
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        new_usage.append(
            extract_usage(
                response, agent="validate", call_type="reasoning", provider=LLM_PROVIDER
            ).__dict__
        )

        # Execute existence checks
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_results = tool_node.invoke({"messages": messages})
            messages.extend(tool_results.get("messages", []))

            # Final reasoning — agent outputs JSON for each valid store
            final_response = llm_with_tools.invoke(messages)
            messages.append(final_response)
            new_usage.append(
                extract_usage(
                    final_response, agent="validate", call_type="followup", provider=LLM_PROVIDER
                ).__dict__
            )

            # Parse validated store JSON blocks from final response
            if hasattr(final_response, "content") and final_response.content:
                content = final_response.content
                validated, review = _extract_json_blocks(content, city, validator_logger)
                new_validated.extend(validated)
                needs_review.extend(review)

        else:
            # No tool calls — extract JSON directly from initial response
            if hasattr(response, "content") and response.content:
                validated, review = _extract_json_blocks(response.content, city, validator_logger)
                new_validated.extend(validated)
                needs_review.extend(review)

    except Exception as e:
        err_msg = f"ValidatorAgent error: {e}"
        validator_logger.error(err_msg)
        new_errors.append(err_msg)

    if needs_review:
        from pending_review import record_pending_review

        for store_dict in needs_review:
            record_pending_review(
                store=store_dict,
                city=city,
                category=category,
                reason="Validator confidence=low — needs human review",
            )

    validator_logger.info(
        "ValidatorAgent DONE | validated=%d stores | flagged_for_review=%d | errors=%d",
        len(new_validated),
        len(needs_review),
        len(new_errors),
    )

    state_update: dict = {"next": "supervisor", "messages": messages, "validator_attempted": True}
    if new_validated:
        state_update["validated_stores"] = new_validated
    if new_errors:
        state_update["errors"] = new_errors
    if new_usage:
        state_update["usage_log"] = new_usage

    return state_update


def storage_agent_node(state: AgentState) -> dict:
    """
    Storage Agent — bounded to save_store_to_db and get_database_stats only.
    Reads validated_stores, writes to MongoDB, returns updated saved_count.
    """
    validated_stores = state.get("validated_stores", [])
    city = state.get("city", "")

    storage_logger.info(
        "StorageAgent START | city=%s | stores_to_save=%d",
        city,
        len(validated_stores),
    )

    llm = get_llm()
    tools = get_storage_tools()
    llm_with_tools = llm.bind_tools(tools)

    stores_text = "\n".join(validated_stores)

    messages = [
        SystemMessage(content=STORAGE_SYSTEM),
        HumanMessage(
            content=(
                f"Save these validated African stores to MongoDB.\n\n"
                f"VALIDATED STORES (one JSON per line):\n{stores_text}"
            )
        ),
    ]

    tool_node = ToolNode(tools)
    new_saved_count = 0
    new_errors: list[str] = []
    save_log: list[str] = []  # raw save_store_to_db results — for eval_agents only
    new_usage: list[dict] = []

    try:
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        new_usage.append(
            extract_usage(
                response, agent="storage", call_type="reasoning", provider=LLM_PROVIDER
            ).__dict__
        )

        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_results = tool_node.invoke({"messages": messages})
            tool_messages = tool_results.get("messages", [])
            messages.extend(tool_messages)

            # Count successful saves from tool output.
            # Only save_store_to_db results go into save_log — get_database_stats
            # results are excluded by checking the originating tool name, so the
            # eval module's dedup-rate calculation isn't polluted by unrelated
            # tool output or unrelated "Error" text elsewhere in the run.
            for msg in tool_messages:
                tool_name = getattr(msg, "name", "")
                if tool_name != "save_store_to_db":
                    continue
                if hasattr(msg, "content") and msg.content:
                    content = str(msg.content)
                    save_log.append(content)
                    if content.startswith("Saved:"):
                        new_saved_count += 1
                        storage_logger.info("StorageAgent: %s", content)
                    elif "Already in database" in content:
                        storage_logger.info("StorageAgent (skip): %s", content)

            # Final step — get database stats + summary
            final = llm_with_tools.invoke(messages)
            messages.append(final)
            new_usage.append(
                extract_usage(
                    final, agent="storage", call_type="followup", provider=LLM_PROVIDER
                ).__dict__
            )
            if hasattr(final, "tool_calls") and final.tool_calls:
                final_tools = tool_node.invoke({"messages": messages})
                messages.extend(final_tools.get("messages", []))

    except Exception as e:
        err_msg = f"StorageAgent error: {e}"
        storage_logger.error(err_msg)
        new_errors.append(err_msg)

    storage_logger.info(
        "StorageAgent DONE | newly_saved=%d | errors=%d",
        new_saved_count,
        len(new_errors),
    )

    state_update: dict = {
        "next": "supervisor",
        "messages": messages,
        "saved_count": state.get("saved_count", 0) + new_saved_count,
        "storage_attempted": True,
    }
    if new_errors:
        state_update["errors"] = new_errors
    if save_log:
        state_update["save_log"] = save_log
    if new_usage:
        state_update["usage_log"] = new_usage

    return state_update


# ── Routing function ───────────────────────────────────────────────────────────


def route_from_supervisor(state: AgentState) -> str:
    """
    Reads state["next"] (set by supervisor_node) and returns the node name.
    This is the conditional edge function — maps supervisor decisions to graph nodes.
    """
    decision = state.get("next", "END")
    logger.info("GRAPH ROUTING → node=%s", decision)
    return decision


# ── Helper: JSON block extractor ───────────────────────────────────────────────


def _extract_json_blocks(
    content: str, city: str, log: logging.Logger
) -> tuple[list[str], list[dict]]:
    """
    Parse JSON store objects from LLM output text.
    Handles both ```json fenced blocks and bare JSON objects.

    Splits results by the "confidence" field the Validator is instructed to
    emit (see VALIDATOR_SYSTEM): "high" confidence stores are returned as
    JSON strings ready for validated_stores (same as before this field
    existed); "low" confidence stores are returned as raw dicts for the
    caller to route to the pending_review queue instead. A missing or
    unrecognized confidence value defaults to "low" — fail toward human
    review rather than silently auto-accepting unclear output.

    Returns:
        (validated_json_strings, low_confidence_dicts)
    """
    import re

    validated: list[str] = []
    needs_review: list[dict] = []

    def _route(obj: dict) -> None:
        confidence = str(obj.get("confidence", "low")).strip().lower()
        if confidence == "high":
            validated.append(json.dumps(obj))
            log.debug("ValidatorAgent: accepted store=%s (high confidence)", obj.get("name"))
        else:
            needs_review.append(obj)
            log.info(
                "ValidatorAgent: flagged for review store=%s (confidence=%s)",
                obj.get("name"),
                confidence,
            )

    def _parse_json_object(raw: str) -> dict | None:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.debug("ValidatorAgent: skipped malformed JSON fragment")
            return None

    # Try fenced code blocks first
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fenced:
        for raw in fenced:
            obj = _parse_json_object(raw)
            if obj and obj.get("name") and (obj.get("city") or city):
                if not obj.get("city"):
                    obj["city"] = city
                _route(obj)
        return validated, needs_review

    # Fallback: bare JSON objects (one per line or multi-line)
    bare = re.findall(r"\{[^{}]+\}", content, re.DOTALL)
    for raw in bare:
        obj = _parse_json_object(raw)
        if obj and obj.get("name") and len(obj) >= 3:
            if not obj.get("city"):
                obj["city"] = city
            _route(obj)

    return validated, needs_review


# ── Graph construction ─────────────────────────────────────────────────────────


def build_supervisor_graph():
    """
    Construct the supervisor-worker StateGraph.

    Nodes:
      supervisor     — routing brain (no LLM calls, pure state logic)
      search_agent   — web search + scraping specialist
      validator_agent — quality gate + dedup specialist
      storage_agent  — MongoDB write specialist

    Edges:
      START → supervisor
      supervisor → search_agent | validator_agent | storage_agent | END
      search_agent → supervisor   (specialists ALWAYS return to supervisor)
      validator_agent → supervisor
      storage_agent → supervisor

    Compiled with recursion_limit=25 to prevent infinite loops.
    """
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("search", search_agent_node)
    graph.add_node("validate", validator_agent_node)
    graph.add_node("storage", storage_agent_node)

    # Entry point
    graph.set_entry_point("supervisor")

    # Supervisor → specialist routing (conditional)
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "search": "search",
            "validate": "validate",
            "storage": "storage",
            "END": END,
        },
    )

    # Specialists always return to supervisor
    graph.add_edge("search", "supervisor")
    graph.add_edge("validate", "supervisor")
    graph.add_edge("storage", "supervisor")

    return graph


def build_supervisor_agent(use_checkpointing: bool = True):
    """
    Compile the supervisor graph with optional MongoDB checkpointing.
    recursion_limit=25 is set at compile time — hard ceiling on routing cycles.
    """
    graph = build_supervisor_graph()

    checkpointer = None
    if use_checkpointing and MONGODB_URI:
        try:
            from langgraph.checkpoint.mongodb import MongoDBSaver
            from pymongo import MongoClient

            mongo_client = MongoClient(MONGODB_URI)
            checkpointer = MongoDBSaver(mongo_client)
            logger.info("Checkpointing enabled (MongoDB)")
        except ImportError:
            logger.warning("langgraph-checkpoint-mongodb not installed — no checkpointing")
        except Exception as e:
            logger.warning("Checkpointer init failed (%s) — running without checkpointing", e)

    return graph.compile(
        checkpointer=checkpointer,
        # recursion_limit at compile time prevents runaway supervisor loops
    )


# ── Run helper ─────────────────────────────────────────────────────────────────


def run_supervisor_for_city(app, city: str, category: str, is_named_store: bool = False) -> dict:
    """
    Run one supervisor pipeline: find + validate + save stores in a city.

    thread_id is unique per city+category so checkpointing state is isolated.
    The recursion_limit=25 in config is the last line of defense against loops.

    Args:
        is_named_store: True when `category` is actually a specific store
            name (the --names / --names-file CLI path), not a store category.
            Changes how the Search Agent phrases its query — see
            search_agent_node for why this distinction matters.
    """
    import uuid

    thread_id = f"supervisor-{city}-{category}-{uuid.uuid4().hex[:8]}"

    logger.info("=" * 60)
    logger.info(
        "SUPERVISOR RUN START | city=%s | category=%s | is_named_store=%s",
        city,
        category,
        is_named_store,
    )
    logger.info("thread_id=%s", thread_id)
    logger.info("=" * 60)

    initial_state: AgentState = {
        "city": city,
        "category": category,
        "is_named_store": is_named_store,
        "messages": [],
        "search_results": [],
        "validated_stores": [],
        "errors": [],
        "saved_count": 0,
        "validator_attempted": False,
        "storage_attempted": False,
        "save_log": [],
        "usage_log": [],
        "next": "",
    }

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 25,  # hard ceiling — set at compile AND invoke time
    }

    result = app.invoke(initial_state, config=config)

    logger.info(
        "SUPERVISOR RUN DONE | city=%s | saved=%d | errors=%d",
        city,
        result.get("saved_count", 0),
        len(result.get("errors", [])),
    )

    if result.get("errors"):
        for err in result["errors"]:
            logger.warning("Run error: %s", err)

    return result
