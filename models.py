# models.py
# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models define the *shape* of data flowing through the agent.
# LangChain uses these for structured output — the LLM is instructed to return
# JSON that matches the schema, and Pydantic validates it automatically.
# ─────────────────────────────────────────────────────────────────────────────

from typing import Optional, List
from pydantic import BaseModel, Field


class StoreInfo(BaseModel):
    """
    Structured representation of an African store in Canada.

    When you pass this to LangChain's structured output chain, the LLM will
    fill in each field from raw scraped text. Pydantic validates the result.
    """

    name: str = Field(description="Full name of the store or business")

    category: str = Field(
        description=(
            "Type of business. One of: 'Grocery', 'Restaurant', 'Clothing', "
            "'Hair & Beauty', 'Market', 'Bakery', 'Other'"
        )
    )

    region_focus: Optional[str] = Field(
        default=None,
        description=(
            "African region the store specialises in, e.g. 'West African', "
            "'East African', 'Pan-African', 'Nigerian', 'Ethiopian', etc."
        ),
    )

    address: Optional[str] = Field(default=None, description="Street address")
    city: Optional[str] = Field(default=None, description="City")
    province: Optional[str] = Field(default=None, description="Province or territory")
    postal_code: Optional[str] = Field(default=None, description="Canadian postal code")

    phone: Optional[str] = Field(default=None, description="Phone number")
    website: Optional[str] = Field(default=None, description="Website URL")
    email: Optional[str] = Field(default=None, description="Email address")

    hours: Optional[str] = Field(
        default=None, description="Opening hours as a plain string"
    )

    # FIX: description was `str` (required) but the LLM sometimes returns null,
    # causing a Pydantic ValidationError and dropping otherwise valid records.
    # Made Optional with a safe default so extraction never fails on this field.
    description: Optional[str] = Field(
        default="An African store serving the local community.",
        description=(
            "A 2-3 sentence description of the store, its products, and its "
            "community significance. Write in an engaging, informative tone."
        ),
    )

    products_and_specialties: Optional[List[str]] = Field(
        default=None,
        description="List of key products or specialties, e.g. ['Jollof rice', 'Egusi soup']",
    )

    source_url: Optional[str] = Field(
        default=None, description="URL this information was extracted from"
    )


class SearchResult(BaseModel):
    """A raw URL + snippet returned by a web search, before scraping."""

    url: str
    title: str
    snippet: str
