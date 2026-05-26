# African Stores Canada — Store Directory Builder

An AI-assisted crawler that finds and catalogues African-focused stores across
Canada, then generates a static HTML directory site.

Built with **LangChain** and a **deterministic pipeline** (plus an optional
LangGraph agent mode). Supports **Ollama** (local) and **AWS Bedrock** (hosted).

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         pipeline.py                             │
│            (deterministic: search → scrape → extract)            │
└───────────────────────────────────┬────────────────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  extractor.py chain  │
                         │  prompt | llm | json │
                         │  → StoreInfo model   │
                         └─────────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ storage.py facade    │
                         │ MongoDB (default)    │
                         │ or SQLite fallback   │
                         └─────────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  generator.py        │
                         │  DB → Static HTML    │
                         └─────────────────────┘
```

---

## LangChain Concepts in This Project

| File | Concept | What you learn |
|---|---|---|
| `extractor.py` | LCEL chain (`prompt \| llm \| parser`) | How chains compose with the pipe operator |
| `extractor.py` | `JsonOutputParser` + Pydantic | How to get structured data out of an LLM |
| `models.py` | `BaseModel` / `Field` | How Pydantic shapes LLM output |
| `agent.py` (optional) | LangGraph agent | A more flexible (but less deterministic) crawl mode |

---

## Setup

### 1. Python environment

```bash
cd african-stores-agent
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and set what you need.

- **MongoDB Atlas (recommended)**: set `MONGODB_URI` (storage defaults to Mongo when present)
- **LLM**:
  - Local: `LLM_PROVIDER=ollama`
  - Hosted: `LLM_PROVIDER=bedrock` plus `AWS_REGION` / `BEDROCK_MODEL_ID`

### 3. Ollama (optional, for local runs)

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

### 4. Edit config (optional)

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

This runs a single city/category crawl using the **pipeline**.

### Step 2 — Full crawl

```bash
python run.py --full
```

This runs all city × category combinations, then generates the site.

### Step 3 — Generate the HTML site

```bash
python run.py --generate
```

Then open `output/index.html` in your browser.

### Check progress any time

```bash
python run.py --stats
```

### Optional — LangGraph agent mode

If you want the more flexible agent-driven approach (useful for experimentation):

```bash
python run.py --agent
python run.py --agent-full
```

---

## Project Structure

```
african-stores-agent/
├── config.py         ← All settings in one place
├── models.py         ← Pydantic data model (StoreInfo)
├── storage.py        ← Storage facade (MongoDB + SQLite)
├── storage_mongo.py  ← MongoDB Atlas backend
├── storage_sqlite.py ← SQLite backend (fallback)
├── extractor.py      ← LangChain LCEL chain (structured extraction)
├── pipeline.py       ← Deterministic crawl pipeline (default)
├── agent.py          ← LangGraph agent (optional)
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
| Saved 0 stores | Increase `MAX_RESULTS_PER_QUERY` or add more directory sites |
| Empty DB in CI | Ensure `MONGODB_URI` secret is set (and Atlas IP access allows GitHub runners) |
