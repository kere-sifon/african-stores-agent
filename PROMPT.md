# CURSOR PROMPT — African Stores Canada Directory Agent
# ─────────────────────────────────────────────────────────────────────────────
# Paste the section(s) below into Cursor's chat to get targeted help.
# Each section is self-contained. Use the one that matches your current task.
# ─────────────────────────────────────────────────────────────────────────────

---

## 🚀 SECTION A — Full Project Bootstrap
*Use this once, when starting the project from scratch.*

```
I'm building an AI agent in Python that crawls the web to find African stores
in Canada and generates a static HTML directory site.

The full codebase is already scaffolded in this project. Read the following
files before doing anything:
1. .cursor/rules — project conventions, tech stack, what NOT to do
2. SKILLS.md — LangChain patterns used in this project
3. TODO.md — current phase and task status

My setup:
- Apple M4 Mac mini, 24GB RAM
- Ollama running locally at http://localhost:11434
- Model: llama3.1:8b
- Python 3.11 via pyenv, no Docker

My first task is Phase 1 setup. Walk me through:
1. Creating the virtualenv with Python 3.11
2. Installing requirements.txt
3. Verifying Ollama is ready
4. Running the single-city test (python run.py)

Show me the exact terminal commands and tell me what a successful run looks like.
```

---

## 🔧 SECTION B — Fix a Specific File
*Use this when a specific module has a bug or needs improvement.*

```
I'm working on the African Stores Canada agent project.

Before writing any code, read:
- .cursor/rules (conventions and patterns to follow)
- SKILLS.md (the correct LangChain patterns for this codebase)
- The file I'm asking you to fix

Problem I'm seeing:
[PASTE ERROR MESSAGE OR DESCRIBE ISSUE HERE]

File with the issue: [tools.py / extractor.py / agent.py / storage.py]

Constraints:
- Follow the LangChain patterns in SKILLS.md exactly
- Do not introduce new dependencies
- Keep the same function signatures — other files depend on them
- Return a full corrected version of the file, not just a snippet
```

---

## 🧠 SECTION C — Implement a TODO Item
*Use this to implement a specific task from TODO.md.*

```
I'm building the African Stores Canada directory agent. 

Read these files first:
- .cursor/rules
- SKILLS.md
- TODO.md (to understand what phase we're in)

I want to implement this TODO item:
[PASTE THE TODO LINE HERE, e.g. "Add deduplication pass: LLM compares near-duplicate names and merges"]

Relevant existing files:
- [list the files this change touches, e.g. storage.py, tools.py]

Requirements:
- Use only libraries already in requirements.txt
- Follow LangChain LCEL patterns from SKILLS.md
- Keep zero-cost constraint (no paid APIs)
- Write the full implementation, not pseudo-code
- Update TODO.md to mark the item complete

After writing the code, tell me how to test it in isolation before plugging it
into the agent.
```

---

## 🕵️ SECTION D — Debug the Agent
*Use this when the ReAct agent is misbehaving.*

```
My LangChain ReAct agent isn't working correctly. 

Read these files first:
- .cursor/rules
- SKILLS.md (especially sections 3 and 9)
- agent.py
- tools.py

Here is the verbose output from the agent run:
[PASTE THE TERMINAL OUTPUT HERE]

The problem: [describe what's wrong — looping, wrong tool calls, bad JSON, etc.]

Debug it by:
1. Identifying the root cause from the trace
2. Explaining the LangChain concept that's failing (so I learn it)
3. Providing the fix — prefer fixing prompts/docstrings before rewriting code
4. Telling me how to confirm the fix worked
```

---

## ✍️ SECTION E — Improve Extraction Quality
*Use this when the LLM extracts bad or incomplete store data.*

```
The extraction chain in extractor.py is producing poor results.

Read these files:
- .cursor/rules
- SKILLS.md (especially sections 2 and 4)
- extractor.py
- models.py

Here is an example of bad output:
[PASTE A STOREINFO DICT WITH THE PROBLEMS HIGHLIGHTED]

The source text it was given:
[PASTE A SAMPLE OF THE RAW SCRAPED TEXT]

The problems are:
[e.g. "description is too generic", "city is always None", "products list is empty"]

Fix the extraction prompt and/or the Pydantic model Field descriptions to
produce better output. Explain why each change helps. Show me how to test
the fix without running the full agent.
```

---

## 🌐 SECTION F — Add a New Tool
*Use this when you want the agent to have a new capability.*

```
I want to add a new tool to my African Stores Canada LangChain agent.

Read these files:
- .cursor/rules
- SKILLS.md (especially section 1)
- tools.py (to understand the existing tool patterns)

New tool I want:
[DESCRIBE WHAT THE TOOL SHOULD DO]

For example: "A tool that takes a store name and city, queries 411.ca to verify
the phone number and address, and returns the verified contact details."

Requirements for the new tool:
- Use the @tool decorator from langchain_core.tools
- Return a string (even on error)
- Write a clear, specific docstring — the agent reads it to decide when to call
- Respect CRAWL_DELAY_SECONDS
- Follow the error handling pattern: catch specific exceptions, return error strings
- Add the new tool to the get_all_tools() registry at the bottom of tools.py

Also tell me: how should I update the agent's ReAct prompt in agent.py to make
the agent aware of when to use this new tool?
```

---

## 📊 SECTION G — Generate & Improve the HTML Site
*Use this when working on generator.py and the output site.*

```
I'm working on the HTML site generator for the African Stores Canada directory.

Read these files:
- .cursor/rules
- generator.py
- output/index.html (if it exists)
- output/stores/ (sample store page if it exists)

What I want to improve:
[DESCRIBE THE CHANGE — e.g. "Add a map view using Leaflet.js",
"Add pagination to the index page", "Improve the store card design",
"Add a 'recently added' section to the homepage"]

Constraints:
- No build step — must be plain HTML/CSS/JS that opens directly in a browser
- No CDN dependencies except Google Fonts and Leaflet (already trusted)
- Keep the existing Fraunces + DM Sans font pairing and CSS variable system
- Regenerate with: python run.py --generate

Provide the updated generator.py with the changes applied to the Jinja2
templates. Also show me a before/after description of the UX change.
```

---

## 🔄 SECTION H — Phase 2 Upgrade (FastAPI)
*Use this when starting Phase 2 from TODO.md.*

```
I'm ready to start Phase 2 of the African Stores Canada project: adding a
FastAPI layer to serve the directory as a live REST API.

Read these files first:
- .cursor/rules
- SKILLS.md
- TODO.md (Phase 2 section)
- storage.py (the existing data layer the API will use)
- models.py (the Pydantic model to return from the API)

Build api.py with:
- GET /stores?city=Toronto&category=Grocery&page=1 — paginated, filtered list
- GET /stores/{id} — single store detail
- GET /stats — totals by city and category
- POST /stores/refresh — triggers agent crawl for a given city (async)
- CORS enabled for http://localhost:3000 (Next.js dev server)

Constraints:
- FastAPI + uvicorn only (no extra ORMs)
- Reuse storage.py functions — don't duplicate DB logic
- Return Pydantic models, not raw dicts
- Add a Makefile target: `make dev` → uvicorn api:app --reload

Tell me what to add to requirements.txt and how to test each endpoint with curl.
```
