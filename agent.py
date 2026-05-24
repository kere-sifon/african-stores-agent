# agent.py
from langchain_classic.agents import create_react_agent, AgentExecutor
from langchain_core.prompts import PromptTemplate

from tools import get_all_tools
from storage import init_db
from config import (
    get_llm,
    llm_config_summary,
    TARGET_CITIES,
    SEARCH_QUERIES,
    MAX_RESULTS_PER_QUERY,
)

REACT_PROMPT = PromptTemplate.from_template(
    """You are a research agent that finds African stores in Canada and saves them to a database.

You have access to the following tools:
{tools}

STRICT OUTPUT FORMAT — follow this exactly, no markdown, no bold, no code blocks:

Thought: your reasoning about what to do next
Action: one of [{tool_names}]
Action Input: plain text input with no quotes or formatting
Observation: (this is filled in automatically — do not write it yourself)

... repeat Thought/Action/Action Input as needed ...

Thought: I have finished the task.
Final Answer: brief summary of what was saved

EXAMPLE (study this format carefully):

Thought: I need to search for African grocery stores in Toronto.
Action: search_for_stores
Action Input: African grocery store Toronto Ontario Canada
Observation: TITLE: Adonai African Grocery
URL: https://example.com/adonai
SNIPPET: Adonai African Grocery, 4164 Kingston Rd, Scarborough ON. West African foods.
---

Thought: I found a store. Let me scrape the page for more details.
Action: scrape_page
Action Input: https://example.com/adonai
Observation: Adonai African Grocery Store located at 4164 Kingston Rd Scarborough ON M1E 2M4. Phone 416-555-0100. Open daily. Sells Nigerian and Ghanaian groceries.

Thought: I have enough details to save this store.
Action: save_store_to_db
Action Input: {{"name": "Adonai African Grocery", "category": "Grocery", "region_focus": "West African", "address": "4164 Kingston Rd", "city": "Scarborough", "province": "Ontario", "postal_code": "M1E 2M4", "phone": "416-555-0100", "description": "A West African grocery store in Scarborough carrying Nigerian and Ghanaian staples.", "source_url": "https://example.com/adonai"}}
Observation: Saved: Adonai African Grocery (Scarborough)

Thought: I have finished saving the store.
Final Answer: Saved 1 store: Adonai African Grocery in Scarborough.

RULES:
1. Action Input is ALWAYS plain text — never use quotes around it, never write code
2. If scrape_page returns a 403 or 400 error, skip that URL and try the NEXT one
3. If ALL scrape attempts fail, save the store using information from the search snippet alone
4. Never call search_for_stores more than twice — use what you already found
5. Save JSON must use double quotes, no trailing commas

Begin!

Task: {input}

{agent_scratchpad}"""
)


def build_agent() -> AgentExecutor:
    llm = get_llm()
    print(f"[agent] LLM: {llm_config_summary()}")

    tools = get_all_tools()
    agent = create_react_agent(llm=llm, tools=tools, prompt=REACT_PROMPT)

    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=25,
        handle_parsing_errors=(
            "Output format error. You MUST use exactly:\n"
            "Thought: ...\nAction: ...\nAction Input: ...\n"
            "No markdown, no bold, no code blocks."
        ),
        return_intermediate_steps=True,
    )
    return executor


def run_agent_for_city(executor: AgentExecutor, city: str, category: str) -> dict:
    task = (
        f"Find {category}s in {city}, Canada. "
        f"Search once, scrape up to {MAX_RESULTS_PER_QUERY} result URLs, "
        f"extract store details, and save each valid store to the database. "
        f"If a page returns a 403 or 400 error, skip it and try the next URL. "
        f"If scraping fails entirely, save using snippet text only."
    )
    print(f"\n{'='*60}")
    print(f"TASK: {task}")
    print(f"{'='*60}\n")
    return executor.invoke({"input": task})


def run_full_crawl():
    init_db()
    executor = build_agent()

    total_tasks = len(TARGET_CITIES) * len(SEARCH_QUERIES)
    completed = 0

    for city in TARGET_CITIES:
        for query in SEARCH_QUERIES:
            completed += 1
            print(f"\n[{completed}/{total_tasks}] City: {city} | Category: {query}")
            try:
                run_agent_for_city(executor, city, query)
            except Exception as e:
                print(f"  [agent] Error on ({city}, {query}): {e} — continuing...")
                continue

    print("\n✅ Crawl complete.")
    from storage import get_stats
    stats = get_stats()
    print(f"   Total stores collected: {stats['total']}")


if __name__ == "__main__":
    run_full_crawl()