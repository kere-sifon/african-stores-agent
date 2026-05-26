# agent.py
# ─────────────────────────────────────────────────────────────────────────────
# LangGraph agent — production-grade replacement for the ReAct AgentExecutor.
#
# WHY LANGGRAPH OVER REACT AGENTEXECUTOR?
#   The old agent used langchain_classic's AgentExecutor which parses
#   Thought/Action/Observation from raw LLM text. Small models break this
#   format constantly. LangGraph uses native tool calling instead — the LLM
#   outputs structured JSON ({"name": "scrape_page", "args": {...}}) which
#   Claude Haiku on Bedrock handles reliably.
#
# KEY CONCEPTS:
#   StateGraph   — a directed graph where each node transforms agent state
#   AgentState   — explicit typed dict holding the full conversation + metadata
#   ToolNode     — a built-in LangGraph node that executes tool calls from state
#   Checkpointer — persists state to MongoDB so runs survive crashes/restarts
#   bind_tools() — attaches tool schemas to the LLM so it knows what's available
#
# FLOW:
#   START → agent_node → (tool_calls?) → tools_node → agent_node → ... → END
#   The LLM decides when it's done by outputting a message with no tool calls.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from config import (
    MAX_RESULTS_PER_QUERY,
    MONGODB_URI,
    SEARCH_QUERIES,
    TARGET_CITIES,
    get_llm,
    llm_config_summary,
)
from storage import init_db, get_stats
from tools import get_all_tools


# ── Agent state ────────────────────────────────────────────────────────────────
# State is the single source of truth passed between every node in the graph.
# Annotated[list, operator.add] means new messages are appended, not replaced.

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    city: str
    category: str
    stores_saved: int


# ── System prompt ──────────────────────────────────────────────────────────────
# With tool calling, we don't need the rigid Thought/Action/Observation format.
# The model decides what to call natively — the prompt focuses on intent.

SYSTEM_PROMPT = """You are a research agent that finds African stores in Canada \
and saves them to a directory database.

Your job for each task:
1. Search for stores using search_for_stores
2. Scrape promising URLs using scrape_page (skip 403/400 errors, try the next URL)
3. Save each real African store using save_store_to_db
4. Check check_store_exists before saving to avoid duplicates
5. Stop when you have saved the top results or exhausted the search

Rules:
- Save stores that have a physical address, phone number, OR a store website
- Skip social media pages, news articles, blog posts, and major chains
- If scraping fails for all URLs, save using snippet text from the search results
- Call get_database_stats once at the start to see what is already saved
- Do not search more than twice for the same task"""


# ── Graph nodes ────────────────────────────────────────────────────────────────

def agent_node(state: AgentState) -> dict:
    """
    The reasoning node. LLM reads the current state and decides:
      - Call a tool (returns a message with tool_calls populated)
      - Finish (returns a plain message with no tool_calls)
    """
    llm = get_llm()
    tools = get_all_tools()

    # bind_tools attaches tool schemas to the LLM request so it knows
    # what tools exist and what arguments each one expects.
    llm_with_tools = llm.bind_tools(tools)

    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """
    Routing function — inspects the last message to decide next node.
    If the LLM made tool calls → route to 'tools' node.
    If no tool calls → the agent is done → route to END.
    """
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ── Graph construction ─────────────────────────────────────────────────────────

def build_graph():
    """
    Construct the LangGraph StateGraph.

    Nodes:
      agent — LLM reasoning (decides what to do next)
      tools — executes the tool calls the LLM requested

    Edges:
      START → agent
      agent → tools (when LLM made tool calls)
      agent → END   (when LLM is done)
      tools → agent (always loop back after tool execution)
    """
    tools = get_all_tools()

    # ToolNode is a built-in LangGraph node that:
    #   1. Reads tool_calls from the last message in state
    #   2. Executes each tool with its arguments
    #   3. Appends ToolMessage results back to state
    tool_node = ToolNode(tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph


def build_agent(use_checkpointing: bool = True):
    """
    Compile the graph into a runnable app.

    Checkpointing (MongoDB):
      When MONGODB_URI is set, agent state is persisted after every node.
      If the run crashes, the next invocation with the same thread_id resumes
      from where it stopped rather than starting over.

    NOTE: MongoDBSaver.from_conn_string() returns a context manager, not a
    direct instance. Pass a pymongo MongoClient to the constructor directly.
    """
    graph = build_graph()

    checkpointer = None
    if use_checkpointing and MONGODB_URI:
        try:
            from pymongo import MongoClient
            from langgraph.checkpoint.mongodb import MongoDBSaver

            mongo_client = MongoClient(MONGODB_URI)
            checkpointer = MongoDBSaver(mongo_client)
            print("[agent] Checkpointing enabled (MongoDB)")
        except ImportError:
            print("[agent] langgraph-checkpoint-mongodb not installed — no checkpointing")
        except Exception as e:
            print(f"[agent] Checkpointer init failed ({e}) — running without checkpointing")

    return graph.compile(checkpointer=checkpointer)


# ── Run helpers ────────────────────────────────────────────────────────────────

def run_agent_for_city(app, city: str, category: str) -> dict:
    """
    Run one agent task: find stores of a given category in a given city.

    thread_id gives each run a unique checkpointing key so state is isolated
    between city+category combinations.
    """
    import uuid
    thread_id = f"{city}-{category}-{uuid.uuid4().hex[:8]}"

    task = (
        f"Find {category}s in {city}, Canada. "
        f"Search once, scrape up to {MAX_RESULTS_PER_QUERY} URLs, "
        f"extract store details, and save each valid African store to the database. "
        f"Skip stores already in the database."
    )

    print(f"\n{'='*60}")
    print(f"TASK: {task}")
    print(f"{'='*60}\n")

    initial_state: AgentState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=task),
        ],
        "city": city,
        "category": category,
        "stores_saved": 0,
    }

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    result = app.invoke(initial_state, config=config)

    # Print the final message from the agent
    final_messages = result.get("messages", [])
    if final_messages:
        last = final_messages[-1]
        if hasattr(last, "content") and last.content:
            print(f"\n── Agent summary ──\n{last.content}")

    return result


def run_full_crawl():
    """Full crawl across all cities and categories using the LangGraph agent."""
    init_db()
    print(f"[agent] LLM: {llm_config_summary()}")
    app = build_agent()

    total_tasks = len(TARGET_CITIES) * len(SEARCH_QUERIES)
    completed = 0

    for city in TARGET_CITIES:
        for query in SEARCH_QUERIES:
            completed += 1
            print(f"\n[{completed}/{total_tasks}] City: {city} | Category: {query}")
            try:
                run_agent_for_city(app, city, query)
            except Exception as e:
                print(f"  [agent] Error on ({city}, {query}): {e} — continuing...")

    print("\n✅ Agent crawl complete.")
    stats = get_stats()
    print(f"   Total stores collected: {stats['total']}")


if __name__ == "__main__":
    run_full_crawl()
