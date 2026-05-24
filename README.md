# African Stores Canada — AI Agent Directory Builder

An **agentic AI pipeline** that crawls the web to find and catalogue African
stores across Canada, then generates a static HTML directory site.

Built with **LangChain + Ollama** — designed as a learning project to understand
how LangChain agents, tools, chains, and structured output fit together.

---

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              AgentExecutor               │
                    │  (LangChain ReAct loop)                  │
                    │                                          │
                    │  Thought → Action → Observation → ...    │
                    └────────────────┬────────────────────────┘
                                     │ calls
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                       ▼
   ┌─────────────────┐   ┌────────────────────┐  ┌──────────────────┐
   │ search_for_     │   │   scrape_page       │  │ save_store_to_db │
   │ stores (tool)   │   │   (tool)            │  │ (tool)           │
   │                 │   │                     │  │                  │
   │ DuckDuckGo      │   │ requests +          │  │ SQLite via       │
   │ search          │   │ BeautifulSoup       │  │ storage.py       │
   └─────────────────┘   └────────────────────┘  └──────────────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │  extractor.py chain  │
                          │                      │
                          │  ChatOllama (local)  │
                          │  + JsonOutputParser  │
                          │  → StoreInfo model   │
                          └─────────────────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │  generator.py        │
                          │                      │
                          │  SQLite → Jinja2     │
                          │  → Static HTML site  │
                          └─────────────────────┘
```

---

## LangChain Concepts in This Project

| File | Concept | What you learn |
|---|---|---|
| `agent.py` | `create_react_agent` + `AgentExecutor` | How the ReAct loop works: Thought/Action/Observation |
| `tools.py` | `@tool` decorator | How to give the agent hands — every tool is just a Python function |
| `extractor.py` | LCEL chain (`prompt \| llm \| parser`) | How chains compose with the pipe operator |
| `extractor.py` | `JsonOutputParser` + Pydantic | How to get structured data out of an LLM |
| `agent.py` | `PromptTemplate` | How to craft a ReAct system prompt |
| `models.py` | `BaseModel` / `Field` | How Pydantic shapes LLM output |

---

## Setup

### 1. Python environment

```bash
cd african-stores-agent
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
```

### 2. Ollama model

```bash
# Pull the recommended model if you don't have it
ollama pull llama3.1:8b

# Verify Ollama is running
ollama list
```

> **Model choice:**
> - `llama3.1:8b` — fast, good extraction (recommended)
> - `mistral:7b` — slightly better at following JSON schemas
> - Avoid `qwen2.5-coder:14b` here — it's optimised for code, not text extraction

### 3. Edit config.py (optional)

```python
# config.py
OLLAMA_MODEL = "llama3.1:8b"          # Change model here
TARGET_CITIES = ["Toronto, Ontario"]   # Narrow scope for first run
MAX_RESULTS_PER_QUERY = 2             # Lower = faster, less data
```

---

## Running

### Step 1 — Test with one city first

```bash
python run.py
```

Watch the ReAct trace in your terminal. You'll see:

```
Thought: I should search for African grocery stores in Toronto...
Action: search_for_stores
Action Input: African grocery store Toronto Canada
Observation: TITLE: ...
             URL: https://...
             SNIPPET: ...

Thought: I found some results. Let me scrape the first URL...
Action: scrape_page
Action Input: https://...
...
```

### Step 2 — Full crawl

```bash
python run.py --full
```

This runs all city × category combinations. With `MAX_RESULTS_PER_QUERY=3`
and 5 cities × 7 categories, expect ~105 agent tasks. Budget ~30-60 min.

### Step 3 — Generate the HTML site

```bash
python run.py --generate
```

Then open `output/index.html` in your browser.

### Check progress any time

```bash
python run.py --stats
```

---

## Project Structure

```
african-stores-agent/
├── config.py         ← All settings in one place
├── models.py         ← Pydantic data model (StoreInfo)
├── storage.py        ← SQLite read/write
├── tools.py          ← LangChain @tool functions (agent's hands)
├── extractor.py      ← LangChain LCEL chain (structured extraction)
├── agent.py          ← ReAct agent setup + run loop
├── generator.py      ← Static HTML site generator
├── run.py            ← CLI entry point
├── requirements.txt
└── output/           ← Generated site (created on first generate)
    ├── index.html
    └── stores/
        └── *.html
```

---

## Next Steps / Extensions

- **Add a FastAPI layer** — serve the SQLite data as a REST API
- **Scheduled re-crawl** — launchd plist to run weekly and keep data fresh  
- **Better deduplication** — use your local LLM to merge near-duplicate entries
- **Enrich with Google Places API** — add ratings, photos, reviews
- **Deploy to S3** — `aws s3 sync output/ s3://your-bucket --acl public-read`
- **Add OpenSearch/Elasticsearch** — port your existing log-monitoring ES setup
  for full-text search across the directory

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Connection refused` on Ollama | Run `ollama serve` first |
| LLM outputs invalid JSON | Switch model or lower `OLLAMA_TEMPERATURE` |
| DuckDuckGo rate limits | Increase `CRAWL_DELAY_SECONDS` in config.py |
| Agent loops forever | Lower `max_iterations` in agent.py |
| Empty database after run | Check `verbose=True` output for tool errors |
