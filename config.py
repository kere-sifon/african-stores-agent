# config.py
# Central configuration — edit this or set environment variables before running.

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel

load_dotenv()

# ── LLM provider switch ───────────────────────────────────────────────────────
# "ollama" = local Ollama  |  "bedrock" = AWS Bedrock (Claude Haiku 4.5)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

# ── Ollama settings (when LLM_PROVIDER=ollama) ────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0"))

# ── AWS Bedrock settings (when LLM_PROVIDER=bedrock) ─────────────────────────
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
# Haiku 4.5 must be invoked via inference profile ID (not the foundation-model ID).
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)
BEDROCK_MAX_TOKENS = int(os.getenv("BEDROCK_MAX_TOKENS", "4096"))

# ── Search / crawl settings ────────────────────────────────────────────────────
TARGET_CITIES = [
    "Toronto, Ontario",
    "Montreal, Quebec",
    "Calgary, Alberta",
    "Vancouver, British Columbia",
    "Ottawa, Ontario",
]

SEARCH_QUERIES = [
    "African grocery store",
    "African restaurant",
    "African food market",
    "West African store",
    "East African store",
    "African hair salon",
    "African clothing store",
]

# DuckDuckGo site: operators for business directories (Maps via DDG is unreliable)
DIRECTORY_SITES = [
    "site:diasporastores.ca",
    "site:yelp.ca",
    "site:yellowpages.ca",
    "site:411.ca",
    "site:canadianorglist.com",
]
DIRECTORY_SITES_PER_RUN = int(os.getenv("DIRECTORY_SITES_PER_RUN", "2"))
YELP_LISTINGS_PER_RUN = int(os.getenv("YELP_LISTINGS_PER_RUN", "3"))
DIASPORA_LISTINGS_PER_RUN = int(os.getenv("DIASPORA_LISTINGS_PER_RUN", "2"))

MAX_RESULTS_PER_QUERY = int(os.getenv("MAX_RESULTS_PER_QUERY", "8"))
CRAWL_DELAY_SECONDS = 2

# Legacy — DuckDuckGo does not index Google Maps place URLs reliably
MAPS_SEARCH_ENABLED = os.getenv("MAPS_SEARCH_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)
MAPS_SEARCH_RESULTS = int(os.getenv("MAPS_SEARCH_RESULTS", "6"))

# ── Storage ────────────────────────────────────────────────────────────────────
# sqlite = local file  |  mongodb = MongoDB Atlas (set MONGODB_URI)
_db_default = "mongodb" if os.getenv("MONGODB_URI", "").strip() else "sqlite"
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", _db_default).strip().lower()

DB_PATH = os.getenv("DB_PATH", "african_stores.db")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "african_stores")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "stores")

# Pipeline quality: "contact" = address OR phone OR store website | "address" = street only
STORE_CONTACT_RULE = os.getenv("STORE_CONTACT_RULE", "contact").strip().lower()
# Legacy alias — REQUIRE_ADDRESS=true forces strict street-address-only mode
if os.getenv("REQUIRE_ADDRESS", "").lower() in ("1", "true", "yes"):
    STORE_CONTACT_RULE = "address"


def _active_bedrock_model_id() -> str:
    """Return the Bedrock model or inference profile ID to pass to ChatBedrockConverse."""
    return BEDROCK_MODEL_ID


@lru_cache(maxsize=2)
def get_llm(*, json_mode: bool = False) -> BaseChatModel:
    """
    Return a LangChain chat model for the configured provider.

    Args:
        json_mode: When True, bias the model toward JSON output (extraction chain).
                   Ollama uses format='json'; Bedrock relies on prompt + parser.
    """
    if LLM_PROVIDER == "bedrock":
        from langchain_aws import ChatBedrockConverse

        return ChatBedrockConverse(
            model_id=_active_bedrock_model_id(),
            region_name=AWS_REGION,
            temperature=OLLAMA_TEMPERATURE,
            max_tokens=BEDROCK_MAX_TOKENS,
        )

    if LLM_PROVIDER == "ollama":
        from langchain_ollama import ChatOllama

        kwargs: dict = {
            "model": OLLAMA_MODEL,
            "base_url": OLLAMA_BASE_URL,
            "temperature": OLLAMA_TEMPERATURE,
        }
        if json_mode:
            kwargs["format"] = "json"
        return ChatOllama(**kwargs)

    msg = f"Unknown LLM_PROVIDER={LLM_PROVIDER!r}. Use 'ollama' or 'bedrock'."
    raise ValueError(msg)


def llm_config_summary() -> str:
    """Human-readable summary for logging and smoke tests."""
    if LLM_PROVIDER == "bedrock":
        return f"provider=bedrock model={_active_bedrock_model_id()} region={AWS_REGION}"
    return f"provider=ollama model={OLLAMA_MODEL} url={OLLAMA_BASE_URL}"
