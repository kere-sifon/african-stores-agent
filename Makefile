# Makefile — African Stores Canada Agent
# Run `make help` to see all commands

.PHONY: help setup setup-dev test crawl generate stats clean lint security pre-commit-install test-llm test-extract test-bedrock

PYTHON := .venv/bin/python
PIP    := .venv/bin/pip

# ── Default ────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  African Stores Canada — Dev Commands"
	@echo "  ─────────────────────────────────────"
	@echo "  make setup      Create virtualenv + install dependencies"
	@echo "  make test       Single-city agent test (Toronto)"
	@echo "  make crawl      Full multi-city crawl"
	@echo "  make generate   Build HTML site from database"
	@echo "  make stats      Print database summary"
	@echo "  make clean      Remove generated output and database"
	@echo "  make lint       Run ruff linter"
	@echo "  make security   Run all pre-commit security hooks"
	@echo "  make pre-commit-install  Install git hooks (run once per clone)"
	@echo "  make test-llm   Smoke-test get_llm() (Bedrock or Ollama)"
	@echo "  make test-extract  Test extraction chain on fixture text"
	@echo ""

# ── Setup ──────────────────────────────────────────────────────────────────────
setup:
	python3.11 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo ""
	@echo "✅ Environment ready. Activate with: source .venv/bin/activate"
	@echo "   Optional: make setup-dev && make pre-commit-install"

setup-dev:
	$(PIP) install -r requirements-dev.txt
	@echo "✅ Dev tools installed (pre-commit, bandit, ruff, pip-audit)"

# ── Verify Ollama ──────────────────────────────────────────────────────────────
check-ollama:
	@echo "Checking Ollama..."
	@curl -s http://localhost:11434/api/tags | python3 -c \
		"import sys, json; models=[m['name'] for m in json.load(sys.stdin)['models']]; \
		 print('Models available:', models)"

# ── Run ────────────────────────────────────────────────────────────────────────
test:
	$(PYTHON) run.py

crawl:
	$(PYTHON) run.py --full

generate:
	$(PYTHON) run.py --generate

stats:
	$(PYTHON) run.py --stats

# ── Dev helpers ────────────────────────────────────────────────────────────────
test-search:
	$(PYTHON) -c "from tools import search_for_stores; print(search_for_stores.invoke('African grocery Toronto Canada'))"

test-scrape:
	$(PYTHON) -c "from tools import scrape_page; print(scrape_page.invoke('https://www.yelp.ca/search?find_desc=african+grocery&find_loc=Toronto'))"

test-extract:
	$(PYTHON) -c "\
from extractor import extract_store_info; \
result = extract_store_info(\
  'Mama Africa Grocery at 45 Eglinton Ave Toronto sells jollof rice, egusi, and plantain. Call 416-555-0199.', \
  'Toronto, Ontario'\
); \
print(result)"

test-llm:
	$(PYTHON) -c "\
from config import get_llm, llm_config_summary; \
print(llm_config_summary()); \
llm = get_llm(); \
r = llm.invoke('Reply with one short sentence confirming you are ready.'); \
print(r.content)"

test-bedrock: test-llm test-extract

test-db:
	$(PYTHON) -c "from storage import init_db, get_stats; init_db(); print(get_stats())"

# ── Open site ──────────────────────────────────────────────────────────────────
open:
	open output/index.html

# ── Cleanup ────────────────────────────────────────────────────────────────────
clean-output:
	rm -rf output/

clean-db:
	rm -f african_stores.db

clean: clean-output clean-db
	@echo "✅ Cleaned output and database"

# ── Lint ───────────────────────────────────────────────────────────────────────
lint:
	$(PYTHON) -m ruff check . --fix

security:
	@command -v pre-commit >/dev/null || { echo "Run: make setup-dev"; exit 1; }
	pre-commit run --all-files

pre-commit-install:
	@command -v pre-commit >/dev/null || { echo "Run: make setup-dev"; exit 1; }
	pre-commit install
	@echo "✅ Pre-commit hooks installed — they run on every git commit"

# ── Git ────────────────────────────────────────────────────────────────────────
init-repo:
	git init
	git remote add origin git@github.com:kere-sifon/african-stores-canada.git
	git add .
	git commit -m "feat: initial agent scaffold"
	git push -u origin main
