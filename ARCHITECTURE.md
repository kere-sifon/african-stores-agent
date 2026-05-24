# ARCHITECTURE.md — System Map
# ─────────────────────────────────────────────────────────────────────────────
# Read this to understand how all the pieces connect before making changes.
# ─────────────────────────────────────────────────────────────────────────────

## Full Data Flow

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                         run.py (CLI)                                    │
 │   python run.py          → single city test                             │
 │   python run.py --full   → all cities × all categories                  │
 │   python run.py --generate → build HTML from DB                         │
 │   python run.py --stats    → print DB summary                           │
 └───────────────────────────┬─────────────────────────────────────────────┘
                             │
                             ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                         agent.py                                        │
 │                                                                         │
 │  build_agent()                                                          │
 │    ChatOllama(llama3.1:8b) ─────────────────────────────────────────┐  │
 │    get_all_tools() ──────────────────────────────────────────────┐  │  │
 │    REACT_PROMPT (PromptTemplate)                                 │  │  │
 │                                                                  │  │  │
 │    create_react_agent(llm, tools, prompt) ◄─────────────────────┘──┘  │
 │    AgentExecutor(agent, tools, verbose=True, max_iterations=50)        │
 │                                                                         │
 │  ReAct Loop:                                                            │
 │    Thought ──► Action ──► Observation ──► Thought ──► ... ──► Final    │
 └───────────────────────────┬─────────────────────────────────────────────┘
                             │ calls tools
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
 ┌───────────────┐  ┌─────────────────┐  ┌──────────────────┐
 │  tools.py     │  │  tools.py       │  │  tools.py        │
 │               │  │                 │  │                  │
 │ search_for_   │  │ scrape_page     │  │ save_store_to_db │
 │ stores        │  │                 │  │                  │
 │               │  │ requests +      │  │ → storage.py     │
 │ DuckDuckGo    │  │ BeautifulSoup   │  │ → SQLite DB      │
 └───────────────┘  └────────┬────────┘  └──────────────────┘
                             │ raw text
                             ▼
                   ┌──────────────────────┐
                   │  extractor.py        │
                   │                      │
                   │  LCEL Chain:         │
                   │  prompt              │
                   │    | ChatOllama      │
                   │    | JsonOutputParser│
                   │    → StoreInfo       │
                   └──────────────────────┘
                             │
                             ▼
                   ┌──────────────────────┐        ┌────────────────────┐
                   │  storage.py          │        │  models.py         │
                   │                      │◄───────│                    │
                   │  sqlite3             │        │  StoreInfo(Base    │
                   │  african_stores.db   │        │  Model)            │
                   │                      │        │  SearchResult      │
                   │  save_store()        │        └────────────────────┘
                   │  get_all_stores()    │
                   │  store_exists()      │
                   │  get_stats()         │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  generator.py        │
                   │                      │
                   │  Jinja2 templates    │
                   │  get_all_stores()    │
                   │    ↓                 │
                   │  output/index.html   │
                   │  output/stores/*.html│
                   └──────────────────────┘
```

---

## File Dependency Graph

```
config.py ◄──── agent.py
config.py ◄──── extractor.py
config.py ◄──── tools.py
config.py ◄──── storage.py

models.py ◄──── extractor.py
models.py ◄──── storage.py
models.py ◄──── tools.py

storage.py ◄─── tools.py
storage.py ◄─── generator.py
storage.py ◄─── run.py

tools.py ◄───── agent.py
extractor.py ◄── tools.py   (tools calls extractor internally — optional)

agent.py ◄────── run.py
generator.py ◄── run.py
```

**Coupling rules:**
- `config.py` has no imports from this project — it's the root
- `models.py` has no imports from this project — it's the root
- `storage.py` only imports from `config.py` and `models.py`
- `tools.py` imports from `storage.py`, `models.py`, `config.py`
- `extractor.py` imports from `models.py`, `config.py`
- `agent.py` imports from `tools.py`, `storage.py`, `config.py`
- `generator.py` imports from `storage.py`, `config.py`
- `run.py` imports from `agent.py`, `generator.py`, `storage.py`

> If you need to change `models.py`, audit `storage.py` and `extractor.py` too.

---

## LangChain Component Map

```
┌───────────────────────────────────────────────────────────┐
│  LangChain Components Used                                │
│                                                           │
│  ┌─────────────────┐    ┌──────────────────────────────┐ │
│  │  ChatOllama     │    │  @tool decorator             │ │
│  │  (langchain_    │    │  (langchain_core.tools)      │ │
│  │   ollama)       │    │                              │ │
│  │                 │    │  Used in: tools.py           │ │
│  │  Used in:       │    │  5 tools registered          │ │
│  │  agent.py       │    └──────────────────────────────┘ │
│  │  extractor.py   │                                     │
│  └─────────────────┘    ┌──────────────────────────────┐ │
│                         │  LCEL pipe chain             │ │
│  ┌─────────────────┐    │  prompt | llm | parser       │ │
│  │  AgentExecutor  │    │                              │ │
│  │  + ReAct agent  │    │  Used in: extractor.py       │ │
│  │                 │    └──────────────────────────────┘ │
│  │  Used in:       │                                     │
│  │  agent.py       │    ┌──────────────────────────────┐ │
│  └─────────────────┘    │  JsonOutputParser            │ │
│                         │  + Pydantic StoreInfo        │ │
│  ┌─────────────────┐    │                              │ │
│  │  DuckDuckGo     │    │  Used in: extractor.py       │ │
│  │  SearchResults  │    └──────────────────────────────┘ │
│  │                 │                                     │
│  │  Used in:       │    ┌──────────────────────────────┐ │
│  │  tools.py       │    │  ChatPromptTemplate          │ │
│  └─────────────────┘    │  PromptTemplate              │ │
│                         │                              │ │
│                         │  Used in:                    │ │
│                         │  extractor.py, agent.py      │ │
│                         └──────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

---

## SQLite Schema

```sql
CREATE TABLE stores (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     TEXT NOT NULL,
    category                 TEXT,           -- Grocery | Restaurant | Clothing | ...
    region_focus             TEXT,           -- West African | Nigerian | Pan-African | ...
    address                  TEXT,
    city                     TEXT,
    province                 TEXT,
    postal_code              TEXT,
    phone                    TEXT,
    website                  TEXT,
    email                    TEXT,
    hours                    TEXT,
    description              TEXT,
    products_and_specialties TEXT,           -- JSON array: ["jollof rice", "egusi"]
    source_url               TEXT,
    created_at               DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, city)                       -- deduplication constraint
);
```

---

## Phase Roadmap

```
Phase 1 ─── Core pipeline (current)
  └── agent + tools + extractor + SQLite + static HTML

Phase 2 ─── Data quality
  └── deduplication LLM pass + multi-source scraping + re-crawl mode

Phase 3 ─── FastAPI layer
  └── REST API serving SQLite + POST /refresh trigger

Phase 4 ─── Next.js frontend
  └── App Router + shadcn/ui + Tailwind, fetching from Phase 3 API

Phase 5 ─── Deploy & automate
  └── AWS (EC2/S3/CloudFront) + GitHub Actions CI + weekly cron crawl
```
