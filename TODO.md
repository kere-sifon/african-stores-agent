# TODO — African Stores Canada Directory
# ─────────────────────────────────────────────────────────────────────────────
# Status: [ ] todo  [x] done  [~] in progress  [!] blocked
# Update this file as you work. Cursor uses it to understand project state.
# ─────────────────────────────────────────────────────────────────────────────

## Phase 1 — Core Agent Pipeline
> Goal: Agent can autonomously search → scrape → extract → save stores.

### Setup
- [ ] Create Python 3.11 virtualenv (`python3.11 -m venv .venv`)
- [ ] Install requirements (`pip install -r requirements.txt`)
- [ ] Verify Ollama running with llama3.1:8b (`ollama pull llama3.1:8b`)
- [ ] Confirm `python run.py` (single-city test) completes without errors

### Data Collection
- [ ] Confirm DuckDuckGo search tool returns results (test: `python -c "from tools import search_for_stores; print(search_for_stores.invoke('African grocery Toronto'))"`)
- [ ] Confirm scrape_page fetches and cleans text correctly
- [ ] Confirm extractor returns valid StoreInfo from raw text
- [ ] Confirm save_store_to_db writes to SQLite correctly
- [ ] Run single-city test: Toronto + "African grocery store"
- [ ] Validate DB has at least 2-3 stores after test run
- [ ] Run full crawl: `python run.py --full`

### Quality
- [ ] Review 10 extracted store records for accuracy
- [ ] Audit for false positives (non-African stores slipping through)
- [ ] Tune extraction prompt if descriptions are poor quality
- [ ] Add `region_focus` validation (West/East/North/Pan-African)

### Site Generation
- [ ] Generate site: `python run.py --generate`
- [ ] Open `output/index.html` — verify all cards render correctly
- [ ] Test search/filter on index page
- [ ] Open 3 store detail pages — verify all info sections render
- [ ] Fix any Jinja2 template errors


## Phase 2 — Data Quality & Enrichment
> Goal: Higher accuracy, richer data, fresher results.

- [ ] Add a deduplication pass: LLM compares near-duplicate names and merges
- [ ] Add Google Maps scraping (parse google.com/maps search results directly)
- [ ] Add Yelp directory scraping (yelp.ca/search?find_desc=african)
- [ ] Add 411.ca scraping for phone/address verification
- [ ] Store a `last_verified` timestamp per record
- [ ] Add a re-crawl mode: `python run.py --refresh` updates stale records
- [ ] Add confidence score: did we get name+address+phone vs just name?
- [ ] Enrich with `products_and_specialties` for more stores (second-pass LLM)


## Phase 3 — FastAPI + Search Layer
> Goal: Serve the directory as a live API, not just static HTML.

- [ ] Add `fastapi` and `uvicorn` to requirements
- [ ] Create `api.py` with endpoints:
  - `GET /stores` — paginated list with city/category filters
  - `GET /stores/{id}` — single store detail
  - `GET /stats` — counts by city/category
  - `POST /stores/refresh` — trigger re-crawl for a city
- [ ] Add full-text search to `/stores` (SQLite FTS5 or simple LIKE)
- [ ] Add CORS headers for local frontend development
- [ ] Write a `Makefile` with `make dev`, `make crawl`, `make generate`
- [ ] Create launchd plist for weekly re-crawl on Mac mini


## Phase 4 — Next.js Frontend
> Goal: Replace static HTML with a proper React app using existing Next.js skills.

- [ ] Scaffold `frontend/` with Next.js 14 App Router + TypeScript
- [ ] Implement `/` — homepage with featured stores and city filter
- [ ] Implement `/stores` — directory grid with search
- [ ] Implement `/stores/[slug]` — individual store page
- [ ] Connect to FastAPI via `fetch` (Phase 3 must be done first)
- [ ] Add Tailwind + shadcn/ui
- [ ] Deploy frontend to Vercel (free tier, zero cost)


## Phase 5 — Deploy & Automate
> Goal: Live site, auto-refreshing data, zero manual effort.

- [ ] Deploy FastAPI to AWS (EC2 t3.micro free tier or App Runner)
- [ ] Deploy static frontend to S3 + CloudFront
- [ ] Set up GitHub Actions CI: lint → test → deploy on push
- [ ] Add MLflow tracking for extraction quality metrics
- [ ] Weekly crawl via GitHub Actions cron job
- [ ] Add community submission form (store owners can submit their own listing)


## Backlog / Ideas
- [ ] Igbo language support: bilingual store descriptions (ties into Igbo NLP work)
- [ ] Map view: integrate Leaflet.js on the index page
- [ ] RSS feed: `output/feed.xml` with newly added stores
- [ ] Store image scraping: grab logo/cover from Google Images
- [ ] Social links extractor: Instagram, Facebook handles from store websites
- [ ] OpenSearch integration: port ES setup from ai-log-monitoring project
- [ ] Export to CSV: `python run.py --export csv`
- [ ] Telegram/Slack bot: "find me an African grocery near Scarborough"


## Known Issues
- DuckDuckGo rate-limits after ~20 requests; add randomised delay jitter
- Some scraped pages are JavaScript-rendered (need Playwright for those)
- LLM occasionally hallucinates addresses — need address validation step
- `mistral:7b` sometimes outputs markdown fences inside JSON mode — strip them


## Notes for Cursor
When working on this project:
1. Check TODO.md first to understand what phase we're in
2. Check SKILLS.md for the correct LangChain pattern before writing any agent code
3. Check .cursor/rules for project-wide conventions
4. Never modify models.py without updating storage.py — they are coupled
5. Test tools in isolation before testing the full agent loop
