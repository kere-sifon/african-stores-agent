# generator.py
# ─────────────────────────────────────────────────────────────────────────────
# Reads all stores from the configured database and generates:
#   output/index.html         — main directory page (search + filter)
#   output/stores/<slug>.html — individual store page
#
# Run this after the agent crawl: python generator.py
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import json
from pathlib import Path
from jinja2 import Environment, BaseLoader
from storage import get_all_stores, init_db
from config import OUTPUT_DIR

OUTPUT_PATH = Path(OUTPUT_DIR)
STORES_PATH = OUTPUT_PATH / "stores"


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text).strip("-")


# ── Templates ──────────────────────────────────────────────────────────────────

INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>African Stores Canada — Directory</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,700;1,9..144,300&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --ink: #0f0e0c;
      --paper: #f5f0e8;
      --accent: #c84b11;
      --accent2: #2d6a4f;
      --muted: #7a7468;
      --card-bg: #fffdf8;
      --border: #ddd8cc;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'DM Sans', sans-serif;
      background: var(--paper);
      color: var(--ink);
      min-height: 100vh;
    }

    /* ── Hero ── */
    .hero {
      background: var(--ink);
      color: var(--paper);
      padding: 5rem 2rem 4rem;
      text-align: center;
      position: relative;
      overflow: hidden;
    }
    .hero::before {
      content: '';
      position: absolute;
      inset: 0;
      background: repeating-linear-gradient(
        45deg, transparent, transparent 40px,
        rgba(200,75,17,0.06) 40px, rgba(200,75,17,0.06) 41px
      );
    }
    .hero-eyebrow {
      font-family: 'DM Sans', sans-serif;
      font-size: 0.75rem;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 1rem;
    }
    .hero h1 {
      font-family: 'Fraunces', serif;
      font-size: clamp(2.5rem, 6vw, 5rem);
      font-weight: 700;
      line-height: 1.05;
      margin-bottom: 1.25rem;
    }
    .hero h1 em { font-style: italic; color: #e8845a; }
    .hero p {
      font-size: 1.1rem;
      color: #bdb9b2;
      max-width: 500px;
      margin: 0 auto 2.5rem;
      line-height: 1.6;
    }
    .stats-bar {
      display: flex;
      justify-content: center;
      gap: 3rem;
      flex-wrap: wrap;
    }
    .stat { text-align: center; }
    .stat-num {
      font-family: 'Fraunces', serif;
      font-size: 2rem;
      font-weight: 300;
      color: var(--paper);
    }
    .stat-label { font-size: 0.75rem; color: #8a8680; letter-spacing: 0.1em; text-transform: uppercase; }

    /* ── Controls ── */
    .controls {
      max-width: 1100px;
      margin: 2.5rem auto;
      padding: 0 2rem;
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
      align-items: center;
    }
    .search-wrap { flex: 1; min-width: 240px; position: relative; }
    .search-wrap input {
      width: 100%;
      padding: 0.75rem 1rem 0.75rem 2.75rem;
      border: 2px solid var(--border);
      background: var(--card-bg);
      border-radius: 8px;
      font-size: 0.95rem;
      font-family: inherit;
      color: var(--ink);
      transition: border-color 0.2s;
    }
    .search-wrap input:focus { outline: none; border-color: var(--accent); }
    .search-icon {
      position: absolute;
      left: 0.85rem;
      top: 50%;
      transform: translateY(-50%);
      color: var(--muted);
      font-size: 1rem;
    }
    select {
      padding: 0.75rem 1rem;
      border: 2px solid var(--border);
      background: var(--card-bg);
      border-radius: 8px;
      font-size: 0.9rem;
      font-family: inherit;
      color: var(--ink);
      cursor: pointer;
    }
    select:focus { outline: none; border-color: var(--accent); }

    /* ── Grid ── */
    .grid {
      max-width: 1100px;
      margin: 0 auto 4rem;
      padding: 0 2rem;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 1.5rem;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      text-decoration: none;
      color: inherit;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
    }
    .card:hover {
      transform: translateY(-3px);
      box-shadow: 0 8px 24px rgba(0,0,0,0.08);
      border-color: var(--accent);
    }
    .card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; }
    .card h2 {
      font-family: 'Fraunces', serif;
      font-size: 1.15rem;
      font-weight: 700;
      line-height: 1.25;
    }
    .badge {
      display: inline-block;
      padding: 0.2rem 0.6rem;
      border-radius: 20px;
      font-size: 0.7rem;
      font-weight: 500;
      letter-spacing: 0.04em;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .badge-grocery  { background: #e8f5e9; color: #2d6a4f; }
    .badge-restaurant { background: #fff3e0; color: #c84b11; }
    .badge-clothing { background: #e8eaf6; color: #3949ab; }
    .badge-hair     { background: #fce4ec; color: #c2185b; }
    .badge-market   { background: #f3e5f5; color: #7b1fa2; }
    .badge-other    { background: #f5f0e8; color: #5a5248; }

    .card-location { font-size: 0.82rem; color: var(--muted); }
    .card-region {
      font-size: 0.78rem;
      color: var(--accent2);
      font-weight: 500;
      letter-spacing: 0.03em;
    }
    .card p {
      font-size: 0.88rem;
      line-height: 1.55;
      color: #4a4640;
      flex: 1;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .card-arrow {
      font-size: 0.82rem;
      color: var(--accent);
      font-weight: 500;
      align-self: flex-end;
    }

    .no-results {
      grid-column: 1/-1;
      text-align: center;
      padding: 4rem 2rem;
      color: var(--muted);
    }
    .no-results p { font-size: 1.1rem; margin-top: 0.5rem; }

    footer {
      text-align: center;
      padding: 2rem;
      font-size: 0.8rem;
      color: var(--muted);
      border-top: 1px solid var(--border);
    }
  </style>
</head>
<body>

<header class="hero">
  <p class="hero-eyebrow">Canada's African Community</p>
  <h1>African Stores<br><em>Directory</em></h1>
  <p>Discover African groceries, restaurants, markets, and services across Canada.</p>
  <div class="stats-bar">
    <div class="stat">
      <div class="stat-num">{{ stores|length }}</div>
      <div class="stat-label">Listings</div>
    </div>
    <div class="stat">
      <div class="stat-num">{{ cities|length }}</div>
      <div class="stat-label">Cities</div>
    </div>
    <div class="stat">
      <div class="stat-num">{{ categories|length }}</div>
      <div class="stat-label">Categories</div>
    </div>
  </div>
</header>

<div class="controls">
  <div class="search-wrap">
    <span class="search-icon">🔍</span>
    <input type="text" id="search" placeholder="Search stores, cities, specialties…">
  </div>
  <select id="city-filter">
    <option value="">All Cities</option>
    {% for city in cities %}<option value="{{ city }}">{{ city }}</option>{% endfor %}
  </select>
  <select id="cat-filter">
    <option value="">All Categories</option>
    {% for cat in categories %}<option value="{{ cat }}">{{ cat }}</option>{% endfor %}
  </select>
</div>

<div class="grid" id="grid">
{% for store in stores %}
  {% set badge_class = 'badge-' + store.category|lower|replace(' & ', '-')|replace(' ', '-') %}
  <a class="card"
     href="stores/{{ store.slug }}.html"
     data-name="{{ store.name|lower }}"
     data-city="{{ store.city or '' }}"
     data-category="{{ store.category or '' }}"
     data-desc="{{ store.description|lower }}">
    <div class="card-header">
      <h2>{{ store.name }}</h2>
      <span class="badge badge-{{ store.category|lower|replace(' & ', '')|replace(' ', '') }}">
        {{ store.category }}
      </span>
    </div>
    {% if store.region_focus %}<div class="card-region">{{ store.region_focus }}</div>{% endif %}
    {% if store.city %}<div class="card-location">📍 {{ store.city }}{% if store.province %}, {{ store.province }}{% endif %}</div>{% endif %}
    <p>{{ store.description }}</p>
    <span class="card-arrow">View details →</span>
  </a>
{% endfor %}
  <div class="no-results" id="no-results" style="display:none">
    <span style="font-size:2rem">🔍</span>
    <p>No stores match your search.</p>
  </div>
</div>

<footer>Built with a local AI agent · Data sourced from public web listings</footer>

<script>
  const search = document.getElementById('search');
  const cityFilter = document.getElementById('city-filter');
  const catFilter = document.getElementById('cat-filter');
  const cards = document.querySelectorAll('.card');
  const noResults = document.getElementById('no-results');

  function filterCards() {
    const q = search.value.toLowerCase();
    const city = cityFilter.value;
    const cat = catFilter.value;
    let visible = 0;
    cards.forEach(card => {
      const matchQ = !q || card.dataset.name.includes(q) || card.dataset.desc.includes(q);
      const matchCity = !city || card.dataset.city === city;
      const matchCat = !cat || card.dataset.category === cat;
      const show = matchQ && matchCity && matchCat;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    noResults.style.display = visible === 0 ? 'block' : 'none';
  }
  search.addEventListener('input', filterCards);
  cityFilter.addEventListener('change', filterCards);
  catFilter.addEventListener('change', filterCards);
</script>
</body>
</html>"""


STORE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ store.name }} — African Stores Canada</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,700;1,9..144,400&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root { --ink:#0f0e0c; --paper:#f5f0e8; --accent:#c84b11; --accent2:#2d6a4f; --muted:#7a7468; --card-bg:#fffdf8; --border:#ddd8cc; }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'DM Sans', sans-serif; background: var(--paper); color: var(--ink); }
    .top-bar { background: var(--ink); padding: 1rem 2rem; display: flex; align-items: center; gap: 1rem; }
    .top-bar a { color: #bdb9b2; text-decoration: none; font-size: 0.85rem; }
    .top-bar a:hover { color: var(--paper); }
    .top-bar span { color: #4a4640; }

    .hero { background: var(--ink); color: var(--paper); padding: 4rem 2rem 3rem; }
    .hero-inner { max-width: 800px; margin: 0 auto; }
    .badge { display:inline-block; padding:0.25rem 0.75rem; border-radius:20px; font-size:0.75rem; font-weight:500; margin-bottom:1rem; }
    .badge-grocery{background:#1a3d2b;color:#81c995;}
    .badge-restaurant{background:#3d1a0c;color:#e8845a;}
    .badge-other{background:#2a2822;color:#bdb9b2;}
    h1 { font-family:'Fraunces',serif; font-size:clamp(2rem,5vw,3.5rem); font-weight:700; line-height:1.1; margin-bottom:0.75rem; }
    .region { color: #81c995; font-size: 0.9rem; font-weight: 500; margin-bottom: 1rem; }
    .hero-desc { font-size: 1.1rem; color: #bdb9b2; line-height: 1.65; max-width: 600px; }

    .content { max-width: 800px; margin: 3rem auto; padding: 0 2rem 4rem; }
    .info-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1.25rem; margin-bottom: 2.5rem; }
    .info-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 1.25rem; }
    .info-card-label { font-size: 0.7rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); margin-bottom: 0.4rem; }
    .info-card-value { font-size: 0.95rem; font-weight: 500; word-break: break-word; }
    .info-card-value a { color: var(--accent); text-decoration: none; }
    .info-card-value a:hover { text-decoration: underline; }

    h2 { font-family:'Fraunces',serif; font-size: 1.4rem; margin-bottom: 1rem; }
    .tags { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    .tag { background: var(--paper); border: 1px solid var(--border); border-radius: 20px; padding: 0.3rem 0.8rem; font-size: 0.82rem; color: var(--ink); }

    footer { text-align:center; padding:2rem; font-size:0.8rem; color:var(--muted); border-top:1px solid var(--border); }
  </style>
</head>
<body>

<nav class="top-bar">
  <a href="../index.html">← Directory</a>
  <span>/</span>
  <span style="color:#bdb9b2">{{ store.name }}</span>
</nav>

<header class="hero">
  <div class="hero-inner">
    <div class="badge badge-{{ store.category|lower|replace(' & ','')|replace(' ','') }}">
      {{ store.category }}
    </div>
    <h1>{{ store.name }}</h1>
    {% if store.region_focus %}<div class="region">{{ store.region_focus }}</div>{% endif %}
    <p class="hero-desc">{{ store.description }}</p>
  </div>
</header>

<div class="content">
  <div class="info-grid">
    {% if store.address or store.city %}
    <div class="info-card">
      <div class="info-card-label">📍 Address</div>
      <div class="info-card-value">
        {% if store.address %}{{ store.address }}<br>{% endif %}
        {% if store.city %}{{ store.city }}{% if store.province %}, {{ store.province }}{% endif %}{% endif %}
        {% if store.postal_code %}<br>{{ store.postal_code }}{% endif %}
      </div>
    </div>
    {% endif %}
    {% if store.phone %}
    <div class="info-card">
      <div class="info-card-label">📞 Phone</div>
      <div class="info-card-value"><a href="tel:{{ store.phone }}">{{ store.phone }}</a></div>
    </div>
    {% endif %}
    {% if store.website %}
    <div class="info-card">
      <div class="info-card-label">🌐 Website</div>
      <div class="info-card-value"><a href="{{ store.website }}" target="_blank" rel="noopener">Visit website</a></div>
    </div>
    {% endif %}
    {% if store.hours %}
    <div class="info-card">
      <div class="info-card-label">🕐 Hours</div>
      <div class="info-card-value">{{ store.hours }}</div>
    </div>
    {% endif %}
    {% if store.email %}
    <div class="info-card">
      <div class="info-card-label">✉️ Email</div>
      <div class="info-card-value"><a href="mailto:{{ store.email }}">{{ store.email }}</a></div>
    </div>
    {% endif %}
  </div>

  {% if store.products_and_specialties %}
  <h2>Products & Specialties</h2>
  <div class="tags" style="margin-bottom:2.5rem">
    {% for item in store.products_and_specialties %}
    <span class="tag">{{ item }}</span>
    {% endfor %}
  </div>
  {% endif %}

  {% if store.source_url %}
  <p style="font-size:0.8rem; color:var(--muted)">
    Source: <a href="{{ store.source_url }}" target="_blank" rel="noopener" style="color:var(--accent)">{{ store.source_url }}</a>
  </p>
  {% endif %}
</div>

<footer>African Stores Canada Directory</footer>
</body>
</html>"""


def generate_site():
    """Generate the full static site from the database."""
    init_db()
    stores = get_all_stores()

    if not stores:
        print("No stores in database yet. Run the agent first: python agent.py")
        return

    OUTPUT_PATH.mkdir(exist_ok=True)
    STORES_PATH.mkdir(exist_ok=True)

    # Enrich stores with slugs
    for store in stores:
        store["slug"] = slugify(f"{store['name']}-{store.get('city', '')}")

    cities = sorted({s["city"] for s in stores if s.get("city")})
    categories = sorted({s["category"] for s in stores if s.get("category")})

    env = Environment(loader=BaseLoader())

    # ── Index page ─────────────────────────────────────────────────────────────
    index_tpl = env.from_string(INDEX_TEMPLATE)
    index_html = index_tpl.render(stores=stores, cities=cities, categories=categories)
    (OUTPUT_PATH / "index.html").write_text(index_html, encoding="utf-8")
    print(f"✅ Generated: {OUTPUT_PATH}/index.html")

    # ── Store pages ────────────────────────────────────────────────────────────
    store_tpl = env.from_string(STORE_TEMPLATE)
    for store in stores:
        html = store_tpl.render(store=store)
        path = STORES_PATH / f"{store['slug']}.html"
        path.write_text(html, encoding="utf-8")

    print(f"✅ Generated: {len(stores)} store pages in {STORES_PATH}/")
    print(f"\n👉 Open {OUTPUT_PATH}/index.html in your browser to view the directory.")


if __name__ == "__main__":
    generate_site()
