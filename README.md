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

### Named store crawl (manual seed list)

When you already know store names, skip broad search and crawl them directly:

```bash
# Pipeline (deterministic — recommended)
python run.py --names "Grocery Africa, The South African Store" --city "Toronto, Ontario"

# From a file (one name per line, # for comments)
python run.py --names-file stores.txt --city "Toronto, Ontario"

# LangGraph agent
python run.py --agent --names "Planet African Market" --city "Toronto, Ontario"
```

**GitHub Actions:** Run workflow **Crawl directory** → mode **names** → paste store names in `store_names` → optional `use_agent` for agent mode.

### City crawl (all categories in one city)

Crawl every search category (grocery, restaurant, market, etc.) in a single city:

```bash
# Pipeline (recommended)
python run.py --city-crawl --city "Montreal, Quebec"

# LangGraph agent
python run.py --agent --city-crawl --city "Calgary, Alberta"
```

**GitHub Actions:** mode **city** → set **city** to e.g. `Toronto, Ontario` → optional **use_agent**.

Use `"City, Province"` format so city filters work correctly (e.g. `Niagara Falls, Ontario`).

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

### Security (develop branch)

Security checks run **locally on every commit** (after you install hooks) and in **GitHub Actions** on push/PR to `develop`.

```bash
make setup-dev
make pre-commit-install   # once per clone — wires hooks into git commit
make security             # run all hooks manually (same as CI)
```

What runs:

| Layer | Tool | Where | Purpose |
|---|---|---|---|
| **Secrets** | Gitleaks | pre-commit + CI | Block keys/tokens in commits and history |
| **SAST (Python)** | Bandit | pre-commit + CI | Insecure patterns (`requests`, SQL, etc.) |
| **SAST (deep)** | CodeQL | CI (`codeql.yml`) | GitHub query-based analysis; results in Security tab |
| **Code quality** | Ruff | pre-commit + CI | Lint (E/F/W/B/S) + format |
| **Dependencies** | pip-audit | CI | CVEs in `requirements.txt` |

**Local commands:**

```bash
make quality    # Ruff + Bandit only (fast)
make security   # Full pre-commit (secrets + quality + file checks)
```

**GitHub workflows:**

| Workflow | Jobs to require on `develop` |
|---|---|
| `security.yml` | Pre-commit, Ruff (lint + format), Bandit (Python SAST), pip-audit, Gitleaks |
| `codeql.yml` | CodeQL (Python) |

Enable **CodeQL** under Settings → Code security → Code scanning (default for public repos; enable for private org repos).

CI uses the open-source [Gitleaks](https://github.com/gitleaks/gitleaks) CLI (no `GITLEAKS_LICENSE` secret).

Dependabot opens weekly update PRs against `develop` (see `.github/dependabot.yml`).

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
