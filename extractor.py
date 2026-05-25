# extractor.py
# ─────────────────────────────────────────────────────────────────────────────
# LCEL extraction chain: prompt | llm | parser
# LLM comes from config.get_llm() (Ollama or AWS Bedrock).
# ─────────────────────────────────────────────────────────────────────────────

from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable

from models import StoreInfo
from config import get_llm, llm_config_summary

_parser = JsonOutputParser(pydantic_object=StoreInfo)

_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are a data extraction assistant. Your job is to extract structured 
information about African stores in Canada from raw web page text.

Rules:
- Extract only information clearly present in the text
- For "name": use the actual business name only, never a page title or URL slug.
  Bad: "African Grocery Delivery Toronto | iLeOja Online African Market"
  Good: "iLeOja Online African Market"
- If a field is not mentioned, omit it or use null
- address: include a street address when present; do not invent one from a social media post alone
- Only extract a business that sells African groceries/food or is an African-focused shop
- Do NOT extract major Canadian supermarket chains (Loblaws, Walmart, Metro, Sobeys, etc.)
- Do NOT extract businesses from news articles, vlogs, or listicles about generic grocery shopping
- Write the description in an engaging, informative tone suitable for a directory

{format_instructions}""",
        ),
        (
            "human",
            """Extract store information from this text. The store is located in: {city_hint}

TEXT:
{page_text}

Return ONLY the JSON object, no other text.""",
        ),
    ]
).partial(format_instructions=_parser.get_format_instructions())


@lru_cache(maxsize=1)
def get_extraction_chain() -> Runnable:
    """Build (and cache) the extraction chain for the current LLM provider."""
    llm = get_llm(json_mode=True)
    return _prompt | llm | _parser


def extract_store_info(page_text: str, city_hint: str = "Canada") -> StoreInfo | None:
    """
    Run the extraction chain on raw page text.
    Returns a validated StoreInfo object, or None if extraction fails.
    """
    try:
        result = get_extraction_chain().invoke(
            {"page_text": page_text[:3500], "city_hint": city_hint}
        )
        if not result or not isinstance(result, dict):
            print("  [extractor] Model returned no JSON object — skipping")
            return None
        return StoreInfo(**result)
    except OutputParserException as e:
        print(f"  [extractor] Parser error: {e}")
        return None
    except Exception as e:
        print(f"  [extractor] Extraction error ({llm_config_summary()}): {e}")
        return None
