# African Stores Canada — Store Directory Builder

An AI-assisted crawler that finds and catalogues African-focused stores across
Canada, then generates a static HTML directory site.

Built with **LangChain**, **LangGraph**, and a **multi-agent supervisor
architecture**. Supports **Ollama** (local) and **AWS Bedrock** (hosted).

---

## Architecture

### Multi-Agent Supervisor (default agent mode)

The agent paths (`--agent`, `--province`, `--agent-full`) use a
**supervisor-worker pattern** with three specialist agents, each with a
bounded tool set. The supervisor owns all routing decisions — specialists
always return to it after completing their step.

```
┌─────────────────────────────────────────────────────────────────┐
│                        supervisor.py                             │
│                                                                  │
│   START → supervisor ──────────────────────────────────────┐    │
│                │                                           │    │
│           ┌────▼────┐    ┌──────────┐    ┌──────────┐     │    │
│           │  search  │───▶│ validate │───▶│ storage  │     │    │
│           │  agent   │    │  agent   │    │  agent   │     │    │
│           └─────────┘    └──────────┘    └──────────┘     │    │
│                │               │               │           │    │
│                └───────────────┴───────────────┘           │    │
│                        always returns to supervisor         │    │
│                                                            ▼    │
│                                                           END   │
└─────────────────────────────────────────────────────────────────┘
```

**Specialist agents and their bounded tool sets:**

| Agent | Tools | Responsibility |
|---|---|---|
| `SearchAgent` | `search_for_stores`, `scrape_page` | Web search + page scraping only |
| `ValidatorAgent` | `check_store_exists` | Quality gate + deduplication check |
| `StorageAgent` | `save_store_to_db`, `get_database_stats` | MongoDB writes only |

**Key design decisions:**
- Supervisor logs every routing decision with the full state snapshot received
  — the primary debuggability mechanism in a multi-agent graph
- `recursion_limit=25` enforced at compile and invoke time
- `validator_attempted` flag prevents the validator re-routing loop when a
  city/category has no valid stores
- Per-agent evaluation scores: search precision, validator accuracy,
  storage new-insert rate

### Deterministic Pipeline (default non-agent mode)

```
┌────────────────────────────────────────────────────────────────┐
│                         pipeline.py                             │
│            (deterministic: search → scrape → extract)           │
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

## LangChain / LangGraph Concepts in This Project

| File | Concept | What you learn |
|---|---|---|
| `extractor.py` | LCEL chain (`prompt \| llm \| parser`) | How chains compose with the pipe operator |
| `extractor.py` | `JsonOutputParser` + Pydantic | How to get structured data out of an LLM |
| `models.py` | `BaseModel` / `Field` | How Pydantic shapes LLM output |
| `supervisor.py` | LangGraph supervisor-worker | Multi-agent orchestration with bounded tool sets |
| `agent.py` | LangGraph single agent | Single-agent mode (retained for reference) |

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

- **MongoDB Atlas (recommended)**: set `MONGODB_URI`
- **LLM**:
  - Local: `LLM_PROVIDER=ollama`
  - Hosted: `LLM_PROVIDER=bedrock` plus `AWS_REGION` / `BEDROCK_MODEL_ID`

### 3. Ollama (optional, for local runs)

```bash
ollama pull llama3.1:8b
ollama list
```

> **Model choice:**
> - `llama3.1:8b` — fast, good extraction (recommended)
> - `mistral:7b` — slightly better at following JSON schemas

### 4. Edit config (optional)

```python
# config.py
OLLAMA_MODEL = "llama3.1:8b"          # Change model here
TARGET_CITIES = ["Toronto, Ontario"]   # Narrow scope for first run
MAX_RESULTS_PER_QUERY = 2             # Lower = faster, less data
```

---

## Running

### Test with one city (agent mode)

```bash
# Supervisor multi-agent (default agent path)
python run.py --agent

# With per-agent eval report
python run_supervisor.py --city "Toronto, Ontario" --eval
```

### Named store crawl (manual seed list)

```bash
# Pipeline (deterministic)
python run.py --names "Grocery Africa, The South African Store" --city "Toronto, Ontario"

# From a file
python run.py --names-file stores.txt --city "Toronto, Ontario"

# Supervisor agent
python run.py --agent --names "Planet African Market" --city "Toronto, Ontario"
```

**GitHub Actions:** mode **names** → paste store names → optional **use_agent**.

### City crawl (all categories in one city)

```bash
# Pipeline
python run.py --city-crawl --city "Montreal, Quebec"

# Supervisor agent
python run.py --agent --city-crawl --city "Calgary, Alberta"
```

**GitHub Actions:** mode **city** → set **city** → optional **use_agent**.

### Province crawl

```bash
# Crawl all cities in a province via supervisor
python run.py --province "Ontario"

# Weekly automatic rotation (used by scheduled cron)
python run.py --province-weekly
```

### Full crawl

```bash
python run.py --agent-full
```

### Generate the HTML site

```bash
python run.py --generate
# Open output/index.html in your browser
```

### Check progress

```bash
python run.py --stats
```

### Dev database testing

Never test against production — use a separate DB name:

```bash
MONGODB_DB_NAME=african_stores_dev python test_supervisor.py --smoke
MONGODB_DB_NAME=african_stores_dev python test_supervisor.py \
  --city "Toronto, Ontario" --category "African grocery store"
```

The test runner hard-stops if `MONGODB_DB_NAME=african_stores` (production).

---

## Testing

```bash
# Smoke + unit tests (no LLM calls, no DB writes — instant)
python test_supervisor.py --smoke

# Full integration test against dev DB
MONGODB_DB_NAME=african_stores_dev python test_supervisor.py \
  --city "Toronto, Ontario" --category "African grocery store"
```

**Test stages:**
1. Graph wiring — all nodes registered, graph compiles
2. Tool boundaries — each agent's tool set is correctly bounded
3. Supervisor routing — all 7 routing cases including failure modes
4. Eval module — search precision, validator accuracy, storage dedup rate
5. Integration — real Bedrock + Atlas end-to-end run

---

## Security

```bash
make setup-dev
make pre-commit-install   # once per clone
make security             # run all hooks manually
```

| Layer | Tool | Where | Purpose |
|---|---|---|---|
| **Secrets** | Gitleaks | pre-commit + CI | Block keys/tokens in commits |
| **SAST (Python)** | Bandit | pre-commit + CI | Insecure patterns |
| **SAST (deep)** | CodeQL | CI (`codeql.yml`) | GitHub query-based analysis |
| **Code quality** | Ruff | pre-commit + CI | Lint + format |
| **Dependencies** | pip-audit | CI | CVEs in `requirements.txt` |

---

## Project Structure

```
african-stores-agent/
├── config.py           ← All settings in one place
├── models.py           ← Pydantic data model (StoreInfo)
├── storage.py          ← Storage facade (MongoDB + SQLite)
├── storage_mongo.py    ← MongoDB Atlas backend
├── storage_sqlite.py   ← SQLite backend (fallback)
├── extractor.py        ← LangChain LCEL chain (structured extraction)
├── pipeline.py         ← Deterministic crawl pipeline
├── supervisor.py       ← Multi-agent supervisor (search/validate/storage)
├── tools_search.py     ← Search Agent bounded tool set
├── tools_validator.py  ← Validator Agent bounded tool set
├── tools_storage.py    ← Storage Agent bounded tool set
├── eval_agents.py      ← Per-agent evaluation scores
├── agent.py            ← Single LangGraph agent (retained for reference)
├── generator.py        ← Static HTML site generator
├── run.py              ← CLI entry point
├── run_supervisor.py   ← Supervisor-only CLI entry point
├── test_supervisor.py  ← 5-stage test suite for supervisor
├── requirements.txt
└── output/             ← Generated site (created on first generate)
    ├── index.html
    └── stores/
        └── *.html
```

---

## Scheduled Crawl (CI)

Weekly Sunday 6am ET — province rotation via GitHub Actions (`crawl.yml`).

- One province per week, 10 provinces × 10 weeks = national coverage every 2.5 months
- 34 cities covered across all provinces
- Each city × category runs through the multi-agent supervisor pipeline
- MongoDB checkpointing enabled in CI for crash recovery
- Email report sent after each run

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Connection refused` on Ollama | Run `ollama serve` first |
| LLM outputs invalid JSON | Switch model or lower `OLLAMA_TEMPERATURE` |
| DuckDuckGo rate limits | Increase `CRAWL_DELAY_SECONDS` in config.py |
| Saved 0 stores | Increase `MAX_RESULTS_PER_QUERY` or add more directory sites |
| Empty DB in CI | Ensure `MONGODB_URI` secret is set |
| Recursion limit hit | Check `validator_attempted` flag in supervisor logs |
| `ResourceNotFoundException` on Bedrock | Enable model access: AWS Console → Bedrock → Model access |
| Pre-commit failures on push | Run `pre-commit run --all-files` locally then re-commit |
