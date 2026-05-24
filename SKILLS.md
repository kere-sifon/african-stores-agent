# SKILLS.md — LangChain Reference for This Project
# ─────────────────────────────────────────────────────────────────────────────
# Quick reference for the LangChain patterns used in this project.
# Read this before asking Cursor to write any LangChain code.
# ─────────────────────────────────────────────────────────────────────────────

## 1. The @tool Decorator

Every tool is a plain Python function decorated with `@tool`.
The agent reads the **docstring** to decide when to call it.
The **function signature** defines the input schema.
The **return value** must always be a string (the observation).

```python
from langchain_core.tools import tool

@tool
def search_for_stores(query: str) -> str:
    """
    Search the web for African stores in Canada.
    Use queries like 'Nigerian grocery Toronto Canada'.
    Returns a list of URLs and snippets.
    """
    # ... implementation
    return "TITLE: ...\nURL: ...\nSNIPPET: ..."
```

**Rules:**
- One argument only (or `_: str = ""` for no-arg tools)
- Always return a string
- Never raise — catch all exceptions and return an error string
- Keep docstrings specific and honest about what the tool returns

---

## 2. LCEL Chains (pipe syntax)

LCEL = LangChain Expression Language. Chains compose with `|`.

```python
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from models import StoreInfo

llm = ChatOllama(model="llama3.1:8b", base_url="http://localhost:11434",
                 temperature=0, format="json")
parser = JsonOutputParser(pydantic_object=StoreInfo)
prompt = ChatPromptTemplate.from_messages([
    ("system", "Extract store info. {format_instructions}"),
    ("human", "{page_text}"),
]).partial(format_instructions=parser.get_format_instructions())

chain = prompt | llm | parser      # ← This is the whole chain
result = chain.invoke({"page_text": "..."})   # result is a dict
store = StoreInfo(**result)                    # validate with Pydantic
```

**Common parsers:**
| Parser | Use for |
|--------|---------|
| `JsonOutputParser` | Structured dicts / Pydantic models |
| `StrOutputParser` | Plain text output |
| `PydanticOutputParser` | Strict Pydantic validation (raises on error) |

---

## 3. ReAct Agent Setup

```python
from langchain_ollama import ChatOllama
from langchain_classic.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import PromptTemplate

llm = ChatOllama(model="llama3.1:8b", base_url="http://localhost:11434")
tools = [search_for_stores, scrape_page, save_store_to_db]

# Prompt MUST contain: {tools}, {tool_names}, {input}, {agent_scratchpad}
prompt = PromptTemplate.from_template("""
You are a research agent. Tools: {tools}
Format: Thought/Action/Action Input/Observation
Task: {input}
{agent_scratchpad}
""")

agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,               # ← prints every Thought/Action/Observation
    max_iterations=30,          # ← safety limit
    handle_parsing_errors=True, # ← recovers from malformed LLM output
    return_intermediate_steps=True,
)
result = executor.invoke({"input": "Find African stores in Toronto"})
```

**How the ReAct loop works:**
```
1. Agent sees task → generates "Thought: ..."
2. Agent outputs "Action: tool_name" + "Action Input: ..."
3. AgentExecutor calls the tool, gets the return value
4. Appends "Observation: <return value>" to scratchpad
5. Agent sees observation → generates next Thought
6. Repeats until agent outputs "Final Answer: ..."
```

---

## 4. Structured Output with Pydantic

```python
from pydantic import BaseModel, Field
from typing import Optional, List

class StoreInfo(BaseModel):
    name: str = Field(description="Full business name")
    category: str = Field(description="One of: Grocery, Restaurant, ...")
    city: Optional[str] = Field(default=None, description="City in Canada")
    description: str = Field(description="2-3 sentence engaging description")
    products: Optional[List[str]] = Field(default=None)
```

**Tips:**
- `Field(description=...)` is injected into the prompt by `JsonOutputParser`
- Use `Optional[X]` (or `X | None`) for fields that may be absent
- Set `default=None` for optional fields — the LLM will omit them cleanly
- `format="json"` on `ChatOllama` enables Ollama's JSON mode for better reliability

---

## 5. ChatOllama Reference

```python
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="llama3.1:8b",             # or "mistral:7b"
    base_url="http://localhost:11434",
    temperature=0,                    # 0 = deterministic (best for extraction)
    format="json",                    # enables JSON mode (use for extraction only)
)
```

**Model guidance for this project:**
| Task | Model | Why |
|------|-------|-----|
| Structured extraction | `llama3.1:8b` | Follows JSON schema reliably |
| Writing descriptions | `mistral:7b` | Better prose quality |
| Agent reasoning | `llama3.1:8b` | Follows ReAct format well |
| Do NOT use | `qwen2.5-coder:14b` | Tuned for code, not text |

---

## 6. DuckDuckGo Search (no API key)

```python
from langchain_community.tools import DuckDuckGoSearchResults

search = DuckDuckGoSearchResults(num_results=5, output_format="list")
results = search.invoke("African grocery store Toronto Canada")
# results → list of dicts: [{snippet, title, link}, ...]
```

**Tips:**
- Add `time.sleep(2)` between searches to avoid rate limits
- Queries should be specific: include city + "Canada" + category
- `num_results=3` is usually enough; more = slower + more rate limit risk

---

## 7. Web Scraping Pattern

```python
import requests
from bs4 import BeautifulSoup
import re, time

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; ...) Chrome/122..."}

def scrape(url: str, max_chars: int = 4000) -> str:
    time.sleep(2)  # always delay
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()[:max_chars]
```

**Why truncate to 4000 chars?**
Local 8B models typically have a 4096–8192 token context window.
After the system prompt and schema instructions, ~4000 chars of page text
is the safe ceiling before you risk truncation errors.

---

## 8. SQLite Patterns

```python
import sqlite3, json

def get_connection():
    conn = sqlite3.connect("african_stores.db")
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    return conn

# INSERT OR IGNORE prevents duplicates
conn.execute("INSERT OR IGNORE INTO stores (...) VALUES (...)", (...,))

# JSON column for lists
json.dumps(["jollof rice", "egusi"])   # store
json.loads(row["products"] or "[]")    # retrieve
```

---

## 9. Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `OutputParserException` | LLM returned non-JSON | Add `handle_parsing_errors=True`; use `format="json"` on ChatOllama |
| `Connection refused` | Ollama not running | Run `ollama serve` |
| `RateLimitError` DDG | Too many searches | Increase `CRAWL_DELAY_SECONDS` |
| Agent loops > max_iterations | LLM stuck | Lower task scope; improve tool docstrings |
| `pydantic ValidationError` | LLM omitted required field | Make field `Optional` with a default |
| Scraped text too long | Large page | Always slice to `[:4000]` before sending to LLM |

---

## 10. Debugging Checklist

```bash
# Is Ollama running?
ollama list

# Does the model respond?
ollama run llama3.1:8b "Say hello in JSON with key 'message'"

# Does the extractor work on fixture text?
python -c "
from extractor import extract_store_info
result = extract_store_info('Mama Africa Grocery, 45 Eglinton Ave, Toronto. West African foods.', 'Toronto')
print(result)
"

# Does a single tool work?
python -c "
from tools import search_for_stores
print(search_for_stores.invoke('African grocery Toronto Canada'))
"

# Is anything in the DB?
python run.py --stats
```
