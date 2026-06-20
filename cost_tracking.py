# cost_tracking.py
# ─────────────────────────────────────────────────────────────────────────────
# Token usage and cost tracking for the multi-agent supervisor pipeline.
#
# WHY THIS EXISTS:
#   Per-agent eval (eval_agents.py) tells you WHAT each specialist did
#   (precision, accuracy, dedup rate). This module tells you WHAT IT COST —
#   tokens and dollars, broken down by agent AND by call type within each
#   agent (each specialist makes 2 LLM calls per run: an initial reasoning
#   step, then a follow-up after tool results come back). That granularity
#   matters: the two calls in a specialist often have very different token
#   profiles (the follow-up call re-sends the growing message history,
#   including all tool results, so it's frequently the more expensive half).
#
# PRICING:
#   Hardcoded for Claude Haiku 4.5, matching both Anthropic's direct API
#   pricing and AWS Bedrock on-demand pricing in standard regions (the two
#   are confirmed to match — see platform.claude.com/docs/en/about-claude/pricing).
#   Verify this hasn't changed before relying on it for budget decisions;
#   pricing pages do change over time.
#
#   Ollama (local) calls report real token counts but $0.00 cost — useful for
#   seeing "what would this have cost on Bedrock" even while testing for free
#   against a local model.
#
# USAGE:
#   from cost_tracking import extract_usage, CallUsage
#   response = llm_with_tools.invoke(messages)
#   usage = extract_usage(response, agent="search", call_type="reasoning")
#   # usage.input_tokens, usage.output_tokens, usage.cost_usd
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("cost_tracking")

# Claude Haiku 4.5 — confirmed matching rates on Anthropic direct API and
# AWS Bedrock on-demand (standard regions) as of June 2026.
# Source: https://platform.claude.com/docs/en/about-claude/pricing
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00


@dataclass
class CallUsage:
    """Token usage + cost for a single LLM invocation."""

    agent: str  # "search" | "validate" | "storage"
    call_type: str  # "reasoning" | "followup" — see module docstring
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    provider: str = "unknown"  # "bedrock" | "ollama" | "unknown"


@dataclass
class RunUsage:
    """Aggregated token usage + cost across one full supervisor run."""

    calls: list[CallUsage] = field(default_factory=list)

    def add(self, usage: CallUsage) -> None:
        self.calls.append(usage)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.calls)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

    def by_agent(self) -> dict[str, dict]:
        """Per-agent rollup: {agent: {input_tokens, output_tokens, cost_usd, calls}}."""
        rollup: dict[str, dict] = {}
        for c in self.calls:
            bucket = rollup.setdefault(
                c.agent,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                },
            )
            bucket["input_tokens"] += c.input_tokens
            bucket["output_tokens"] += c.output_tokens
            bucket["total_tokens"] += c.total_tokens
            bucket["cost_usd"] += c.cost_usd
            bucket["calls"] += 1
        for bucket in rollup.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        return rollup

    def by_agent_and_call_type(self) -> dict[str, dict]:
        """Finer rollup: {"search:reasoning": {...}, "search:followup": {...}, ...}."""
        rollup: dict[str, dict] = {}
        for c in self.calls:
            key = f"{c.agent}:{c.call_type}"
            bucket = rollup.setdefault(
                key,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                },
            )
            bucket["input_tokens"] += c.input_tokens
            bucket["output_tokens"] += c.output_tokens
            bucket["total_tokens"] += c.total_tokens
            bucket["cost_usd"] += c.cost_usd
            bucket["calls"] += 1
        for bucket in rollup.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        return rollup

    def to_dict(self) -> dict:
        """Serializable summary for persistence (crawl_history) and CI artifacts."""
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "by_agent": self.by_agent(),
            "by_agent_and_call_type": self.by_agent_and_call_type(),
        }


def _compute_cost(input_tokens: int, output_tokens: int, provider: str) -> float:
    """Cost in USD. Always $0.00 for Ollama (local, free) regardless of token count."""
    if provider != "bedrock":
        return 0.0
    cost = (input_tokens / 1_000_000) * HAIKU_INPUT_PER_MTOK
    cost += (output_tokens / 1_000_000) * HAIKU_OUTPUT_PER_MTOK
    return round(cost, 6)


def extract_usage(response, agent: str, call_type: str, provider: str = "unknown") -> CallUsage:
    """
    Pull token counts off a LangChain AIMessage response and compute cost.

    Works across providers (ChatBedrockConverse, ChatOllama) because both
    populate the standardized `usage_metadata` attribute on AIMessage.
    Returns a zeroed CallUsage (logged as a warning) if usage_metadata is
    missing — this can happen with some local models/providers that don't
    report token counts, and callers should not crash the agent run over
    missing cost telemetry.
    """
    usage_metadata = getattr(response, "usage_metadata", None)

    if not usage_metadata:
        logger.warning(
            "No usage_metadata on response for agent=%s call_type=%s — "
            "cost tracking unavailable for this call (provider=%s)",
            agent,
            call_type,
            provider,
        )
        return CallUsage(agent=agent, call_type=call_type, provider=provider)

    input_tokens = usage_metadata.get("input_tokens", 0) or 0
    output_tokens = usage_metadata.get("output_tokens", 0) or 0
    total_tokens = usage_metadata.get("total_tokens", input_tokens + output_tokens)
    cost = _compute_cost(input_tokens, output_tokens, provider)

    return CallUsage(
        agent=agent,
        call_type=call_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost,
        provider=provider,
    )


def run_usage_from_state(result_state: dict) -> RunUsage:
    """
    Reconstruct a RunUsage from a completed supervisor run's state.

    result_state["usage_log"] is a list of CallUsage.__dict__ entries
    accumulated across all three specialist agents via AgentState's
    usage_log channel (operator.add). This rebuilds CallUsage objects
    from those dicts for reporting/aggregation.
    """
    run_usage = RunUsage()
    for entry in result_state.get("usage_log", []):
        run_usage.add(CallUsage(**entry))
    return run_usage


def combine_run_usages(run_usages: list[RunUsage]) -> RunUsage:
    """Flatten multiple RunUsage objects (one per city/category) into one."""
    combined = RunUsage()
    for ru in run_usages:
        combined.calls.extend(ru.calls)
    return combined


def aggregate_crawl_usage(run_usages: list[RunUsage]) -> dict:
    """
    Combine RunUsage from multiple (city, category) supervisor runs in one
    crawl (province, province-weekly, agent-full) into a single summary.
    Mirrors eval_agents.aggregate_run_evals's shape for consistency.
    """
    return combine_run_usages(run_usages).to_dict()


def print_usage_report(run_usage: RunUsage, run_label: str = "Run") -> None:
    """Human-readable token/cost report for logs and interview demos."""
    print("\n" + "=" * 60)
    print(f"  TOKEN & COST REPORT — {run_label}")
    print("=" * 60)

    by_agent = run_usage.by_agent()
    for agent in ("search", "validate", "storage"):
        if agent not in by_agent:
            continue
        b = by_agent[agent]
        print(
            f"  {agent:10s}  in={b['input_tokens']:>6}  out={b['output_tokens']:>6}  "
            f"total={b['total_tokens']:>6}  cost=${b['cost_usd']:.6f}  ({b['calls']} calls)"
        )

    print(
        f"\n  TOTAL        in={run_usage.total_input_tokens:>6}  "
        f"out={run_usage.total_output_tokens:>6}  total={run_usage.total_tokens:>6}"
    )
    print(f"  TOTAL COST   ${run_usage.total_cost_usd:.6f}")
    print("=" * 60)
