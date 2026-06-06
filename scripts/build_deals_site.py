#!/usr/bin/env python3
"""Build a static deals website from the local OzBargain deal memory."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MEMORY_FILE = ROOT / "outputs" / "deal_memory.json"
OUTPUT_FILE = ROOT / "docs" / "index.html"


def _money(value) -> str:
    try:
        return f"${int(value):,}"
    except (TypeError, ValueError):
        return "$0"


def _parse_dt(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _category_from_title(title: str) -> str:
    t = title.lower()
    rules = [
        ("Finance", ("home loan", "credit card", "qantas points", "velocity", "insurance", "cashback")),
        ("Computing", ("laptop", "macbook", "ssd", "gaming pc", "keyboard", "mouse", "nas", "monitor")),
        ("Electronics", ("tv", "oled", "qled", "samsung", "iphone", "ipad", "airpods", "headphones")),
        ("Home", ("vacuum", "dyson", "robot", "kitchen", "fridge", "washing", "doorbell")),
        ("Gaming", ("switch", "playstation", "xbox", "nintendo", "steam", "game")),
        ("Automotive", ("car", "suv", "dash cam", "battery", "vehicle")),
        ("Travel", ("flight", "hotel", "travel")),
    ]
    for category, words in rules:
        if any(word in t for word in words):
            return category
    return "Other"


def _merchant_from_title(title: str) -> str:
    match = re.search(r"\s@\s*(.+)$", title)
    return match.group(1).strip() if match else "OzBargain"


def _row_from_memory_item(item: dict) -> dict:
    title = item.get("last_title") or item.get("first_title") or "Untitled deal"
    emailed_at = _parse_dt(item.get("last_emailed_at", ""))
    last_seen_at = _parse_dt(item.get("last_seen_at", ""))
    first_seen_at = _parse_dt(item.get("first_seen_at", ""))
    row = {
        "title": title,
        "link": item.get("link") or "#",
        "node_id": item.get("node_id") or "",
        "savings": int(item.get("last_savings", 0) or 0),
        "best_savings": int(item.get("best_savings", 0) or 0),
        "times_seen": int(item.get("times_seen", 0) or 0),
        "email_count": int(item.get("email_count", 0) or 0),
        "last_emailed_at": emailed_at,
        "last_seen_at": last_seen_at,
        "first_seen_at": first_seen_at,
        "category": _category_from_title(title),
        "merchant": _merchant_from_title(title),
    }
    return row


def load_latest_deals(memory_file: Path = MEMORY_FILE) -> tuple[list[dict], datetime]:
    payload = json.loads(memory_file.read_text())
    rows = []
    for item in payload.get("deals", {}).values():
        row = _row_from_memory_item(item)
        if row["last_emailed_at"] == datetime.min.replace(tzinfo=timezone.utc):
            continue
        rows.append(row)

    if not rows:
        return [], datetime.min.replace(tzinfo=timezone.utc)

    latest = max(row["last_emailed_at"] for row in rows)
    latest_rows = [row for row in rows if row["last_emailed_at"] == latest]
    latest_rows.sort(key=lambda row: row["savings"], reverse=True)
    return latest_rows, latest


def load_all_memory_deals(memory_file: Path = MEMORY_FILE) -> tuple[list[dict], datetime]:
    """Load every remembered deal for the public site filter UI."""
    payload = json.loads(memory_file.read_text())
    rows = [_row_from_memory_item(item) for item in payload.get("deals", {}).values()]
    rows = [row for row in rows if row["savings"] > 0 or row["best_savings"] > 0]
    rows.sort(key=lambda row: (row["savings"], row["best_savings"], row["last_seen_at"]), reverse=True)
    if not rows:
        return [], datetime.min.replace(tzinfo=timezone.utc)
    generated_at = max(
        row["last_emailed_at"] if row["last_emailed_at"] != datetime.min.replace(tzinfo=timezone.utc) else row["last_seen_at"]
        for row in rows
    )
    return rows, generated_at


def deals_from_monitor_run(deals: list[dict], generated_at: datetime | None = None) -> tuple[list[dict], datetime]:
    """Convert live monitor deal dictionaries into website rows."""
    generated_at = generated_at or datetime.now(timezone.utc)
    rows = []
    for deal in deals:
        row = {
            "title": deal.get("title") or "Untitled deal",
            "link": deal.get("link") or "#",
            "node_id": str(deal.get("node_id") or ""),
            "savings": int(deal.get("savings", 0) or 0),
            "best_savings": int(deal.get("best_savings") or deal.get("previous_best_savings") or deal.get("savings", 0) or 0),
            "times_seen": int(deal.get("times_seen", 0) or 0) + 1,
            "email_count": int(deal.get("email_count", 0) or 0) + 1,
            "last_emailed_at": generated_at,
            "category": _category_from_title(deal.get("title", "")),
            "merchant": deal.get("merchant_name") or _merchant_from_title(deal.get("title", "")),
        }
        rows.append(row)
    rows.sort(key=lambda row: row["savings"], reverse=True)
    return rows, generated_at


def render_html(deals: list[dict], generated_at: datetime) -> str:
    total = sum(d["savings"] for d in deals)
    top = deals[0]["savings"] if deals else 0
    categories = sorted({d["category"] for d in deals})
    cards = "\n".join(_render_card(deal, i + 1) for i, deal in enumerate(deals))
    chips = "\n".join(
        f'<button class="chip" data-filter="{escape(category)}">{escape(category)}</button>'
        for category in categories
    )
    generated = generated_at.astimezone().strftime("%d %b %Y, %I:%M %p")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OzBargain Deal Radar</title>
  <style>
    :root {{
      --ink: #17202a;
      --muted: #667085;
      --line: #d8dee4;
      --accent: #d95c00;
      --accent-dark: #9a3f00;
      --good: #137333;
      --bg: #f4f7fb;
      --card: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }}
    header {{
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    .wrap {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; }}
    .topbar {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0; }}
    .brand {{ font-weight: 850; font-size: 20px; }}
    .stamp {{ color: var(--muted); font-size: 13px; }}
    .hero {{ padding: 28px 0 22px; }}
    h1 {{ margin: 0; font-size: 34px; line-height: 1.12; letter-spacing: 0; }}
    .sub {{ margin-top: 8px; max-width: 760px; color: var(--muted); font-size: 15px; line-height: 1.55; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 22px 0 0; }}
    .stat {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .label {{ color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; }}
    .value {{ margin-top: 4px; font-size: 26px; line-height: 1.1; font-weight: 900; }}
    .toolbar {{ display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; padding: 18px 0 12px; }}
    input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      font-size: 15px;
      padding: 12px 13px;
    }}
    .filters {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
    button {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      font-weight: 750;
      padding: 10px 12px;
    }}
    button.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 8px 0 32px; }}
    .card {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 14px;
      min-height: 148px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 15px;
    }}
    .rank {{ color: var(--accent-dark); font-weight: 850; font-size: 12px; }}
    .title {{ display: block; margin-top: 6px; color: var(--ink); text-decoration: none; font-size: 16px; line-height: 1.35; font-weight: 850; }}
    .title:hover {{ color: var(--accent-dark); }}
    .meta {{ margin-top: 10px; color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .pillrow {{ margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; }}
    .pill {{ border: 1px solid #e8edf3; background: #f8fafc; border-radius: 999px; padding: 4px 8px; font-size: 12px; color: var(--muted); }}
    .save {{ text-align: right; color: var(--good); font-size: 24px; font-weight: 950; white-space: nowrap; }}
    .save span {{ display: block; margin-top: 2px; color: var(--muted); font-size: 11px; text-transform: uppercase; }}
    .empty {{ display: none; padding: 28px 0 48px; color: var(--muted); }}
    footer {{ border-top: 1px solid var(--line); padding: 18px 0 28px; color: var(--muted); font-size: 13px; }}
    @media (max-width: 760px) {{
      h1 {{ font-size: 28px; }}
      .topbar, .toolbar {{ display: block; }}
      .stamp, .filters {{ margin-top: 10px; justify-content: flex-start; }}
      .stats, .grid {{ grid-template-columns: 1fr; }}
      .card {{ grid-template-columns: 1fr; }}
      .save {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div class="topbar">
        <div class="brand">OzBargain Deal Radar</div>
        <div class="stamp">Latest run: {escape(generated)}</div>
      </div>
      <section class="hero">
        <h1>Today's best quantified deals</h1>
        <div class="sub">A clean public view of the latest OzBargain monitor run. Deals are ranked by parsed potential saving and link back to the original OzBargain posts.</div>
        <div class="stats">
          <div class="stat"><div class="label">Deals</div><div class="value">{len(deals)}</div></div>
          <div class="stat"><div class="label">Potential Value</div><div class="value">{_money(total)}</div></div>
          <div class="stat"><div class="label">Top Saving</div><div class="value">{_money(top)}</div></div>
        </div>
      </section>
    </div>
  </header>
  <main class="wrap">
    <div class="toolbar">
      <input id="search" placeholder="Search deals, merchants, categories" aria-label="Search deals">
      <div class="filters">
        <button class="chip active" data-filter="All">All</button>
        {chips}
      </div>
    </div>
    <section class="grid" id="deals">
      {cards}
    </section>
    <div class="empty" id="empty">No matching deals.</div>
  </main>
  <footer>
    <div class="wrap">Potential savings are parsed from explicit deal text and should be verified before purchase.</div>
  </footer>
  <script>
    const search = document.querySelector('#search');
    const cards = Array.from(document.querySelectorAll('.card'));
    const buttons = Array.from(document.querySelectorAll('.chip'));
    const empty = document.querySelector('#empty');
    let filter = 'All';

    function applyFilters() {{
      const q = search.value.trim().toLowerCase();
      let shown = 0;
      for (const card of cards) {{
        const inCategory = filter === 'All' || card.dataset.category === filter;
        const inSearch = !q || card.dataset.search.includes(q);
        const visible = inCategory && inSearch;
        card.style.display = visible ? 'grid' : 'none';
        if (visible) shown += 1;
      }}
      empty.style.display = shown ? 'none' : 'block';
    }}

    search.addEventListener('input', applyFilters);
    for (const button of buttons) {{
      button.addEventListener('click', () => {{
        filter = button.dataset.filter;
        buttons.forEach(b => b.classList.toggle('active', b === button));
        applyFilters();
      }});
    }}
  </script>
</body>
</html>
"""


def _render_card(deal: dict, rank: int) -> str:
    title = deal["title"]
    category = deal["category"]
    merchant = deal["merchant"]
    search = " ".join([title, category, merchant]).lower()
    seen = f"Seen {deal['times_seen']}x" if deal["times_seen"] else "New"
    node = f"Node {deal['node_id']}" if deal["node_id"] else "OzBargain"
    return f"""<article class="card" data-category="{escape(category, quote=True)}" data-search="{escape(search, quote=True)}">
  <div>
    <div class="rank">#{rank} · {escape(category)}</div>
    <a class="title" href="{escape(deal['link'], quote=True)}" target="_blank" rel="noopener">{escape(title)}</a>
    <div class="meta">{escape(merchant)} · {escape(node)}</div>
    <div class="pillrow">
      <span class="pill">{escape(seen)}</span>
      <span class="pill">Best {_money(deal['best_savings'])}</span>
      <span class="pill">Emailed {deal['email_count']}x</span>
    </div>
  </div>
  <div class="save">{_money(deal['savings'])}<span>potential</span></div>
</article>"""


def _deal_payload(deals: list[dict]) -> str:
    payload = []
    for deal in deals:
        payload.append({
            "title": deal["title"],
            "link": deal["link"],
            "node_id": deal["node_id"],
            "savings": int(deal["savings"]),
            "best_savings": int(deal["best_savings"]),
            "times_seen": int(deal["times_seen"]),
            "email_count": int(deal["email_count"]),
            "last_emailed_at": deal["last_emailed_at"].isoformat(),
            "last_seen_at": deal.get("last_seen_at", deal["last_emailed_at"]).isoformat(),
            "category": deal["category"],
            "merchant": deal["merchant"],
        })
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def render_jekyll_html(deals: list[dict], generated_at: datetime) -> str:
    total = sum(d["savings"] for d in deals)
    top = deals[0]["savings"] if deals else 0
    categories = sorted({d["category"] for d in deals})
    merchants = sorted({d["merchant"] for d in deals})
    generated = generated_at.astimezone().strftime("%d %b %Y, %I:%M %p")
    category_options = "\n".join(f'<option value="{escape(category, quote=True)}">{escape(category)}</option>' for category in categories)
    merchant_options = "\n".join(f'<option value="{escape(merchant, quote=True)}">{escape(merchant)}</option>' for merchant in merchants)
    deal_json = _deal_payload(deals)

    return f"""---
layout: default
title: Today's best quantified deals
---
<div class="deal-radar">
  <section class="radar-intro">
    <div class="stamp">Latest run: {escape(generated)}</div>
    <p>A public view of every remembered OzBargain opportunity. Adjust the filters to reshape the list from the browser without waiting for a new run.</p>
    <div class="stats">
      <div class="stat"><div class="label">Matching Deals</div><div class="value" id="stat-count">{len(deals)}</div></div>
      <div class="stat"><div class="label">Potential Value</div><div class="value" id="stat-total">{_money(total)}</div></div>
      <div class="stat"><div class="label">Top Saving</div><div class="value" id="stat-top">{_money(top)}</div></div>
    </div>
  </section>
  <div class="toolbar">
    <input id="search" placeholder="Search deals, merchants, categories" aria-label="Search deals">
    <button class="filter-toggle" id="filter-toggle" type="button" aria-expanded="true" aria-controls="filter-panel">Filters</button>
  </div>
  <section class="filter-panel" id="filter-panel">
    <label>
      Category
      <select id="category">
        <option value="All">All categories</option>
        {category_options}
      </select>
    </label>
    <label>
      Merchant
      <select id="merchant">
        <option value="All">All merchants</option>
        {merchant_options}
      </select>
    </label>
    <label>
      Minimum saving
      <input id="min-saving" type="number" min="0" step="50" value="0">
    </label>
    <label>
      Seen at least
      <input id="min-seen" type="number" min="0" step="1" value="0">
    </label>
    <label>
      Sort
      <select id="sort">
        <option value="savings-desc">Savings high to low</option>
        <option value="best-desc">Best ever high to low</option>
        <option value="seen-desc">Most seen</option>
        <option value="emailed-desc">Most emailed</option>
        <option value="recent-desc">Most recent</option>
      </select>
    </label>
    <div class="checks">
      <label><input id="emailed-only" type="checkbox"> Emailed only</label>
      <label><input id="repeat-only" type="checkbox"> Repeated sightings</label>
    </div>
    <button class="reset" id="reset-filters" type="button">Reset</button>
  </section>
  <section class="grid" id="deals">
  </section>
  <div class="empty" id="empty">No matching deals.</div>
  <p class="fineprint">Potential savings are parsed from explicit deal text and should be verified before purchase.</p>
</div>
<script id="deal-data" type="application/json">{deal_json}</script>
<script>
  const deals = JSON.parse(document.querySelector('#deal-data').textContent);
  const els = {{
    search: document.querySelector('#search'),
    category: document.querySelector('#category'),
    merchant: document.querySelector('#merchant'),
    minSaving: document.querySelector('#min-saving'),
    minSeen: document.querySelector('#min-seen'),
    sort: document.querySelector('#sort'),
    emailedOnly: document.querySelector('#emailed-only'),
    repeatOnly: document.querySelector('#repeat-only'),
    reset: document.querySelector('#reset-filters'),
    toggle: document.querySelector('#filter-toggle'),
    panel: document.querySelector('#filter-panel'),
    grid: document.querySelector('#deals'),
    empty: document.querySelector('#empty'),
    statCount: document.querySelector('#stat-count'),
    statTotal: document.querySelector('#stat-total'),
    statTop: document.querySelector('#stat-top'),
  }};

  function money(value) {{
    return '$' + Math.round(value || 0).toLocaleString();
  }}

  function escapeHtml(value) {{
    return String(value || '').replace(/[&<>"']/g, char => ({{
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }}[char]));
  }}

  function matchesSearch(deal, query) {{
    if (!query) return true;
    return [deal.title, deal.merchant, deal.category, deal.node_id].join(' ').toLowerCase().includes(query);
  }}

  function rankDeals(rows) {{
    const sort = els.sort.value;
    const copy = [...rows];
    copy.sort((a, b) => {{
      if (sort === 'best-desc') return (b.best_savings - a.best_savings) || (b.savings - a.savings);
      if (sort === 'seen-desc') return (b.times_seen - a.times_seen) || (b.savings - a.savings);
      if (sort === 'emailed-desc') return (b.email_count - a.email_count) || (b.savings - a.savings);
      if (sort === 'recent-desc') return Date.parse(b.last_seen_at) - Date.parse(a.last_seen_at);
      return (b.savings - a.savings) || (b.best_savings - a.best_savings);
    }});
    return copy;
  }}

  function cardHtml(deal, index) {{
    const node = deal.node_id ? `Node ${{escapeHtml(deal.node_id)}}` : 'OzBargain';
    const seen = deal.times_seen ? `Seen ${{deal.times_seen}}x` : 'New';
    return `<article class="card">
      <div>
        <div class="rank">#${{index + 1}} · ${{escapeHtml(deal.category)}}</div>
        <a class="title" href="${{escapeHtml(deal.link)}}" target="_blank" rel="noopener">${{escapeHtml(deal.title)}}</a>
        <div class="meta">${{escapeHtml(deal.merchant)}} · ${{node}}</div>
        <div class="pillrow">
          <span class="pill">${{seen}}</span>
          <span class="pill">Best ${{money(deal.best_savings)}}</span>
          <span class="pill">Emailed ${{deal.email_count}}x</span>
        </div>
      </div>
      <div class="save">${{money(deal.savings)}}<span>potential</span></div>
    </article>`;
  }}

  function applyFilters() {{
    const query = els.search.value.trim().toLowerCase();
    const minSaving = Number(els.minSaving.value || 0);
    const minSeen = Number(els.minSeen.value || 0);
    const rows = rankDeals(deals.filter(deal => {{
      if (els.category.value !== 'All' && deal.category !== els.category.value) return false;
      if (els.merchant.value !== 'All' && deal.merchant !== els.merchant.value) return false;
      if (deal.savings < minSaving) return false;
      if (deal.times_seen < minSeen) return false;
      if (els.emailedOnly.checked && deal.email_count < 1) return false;
      if (els.repeatOnly.checked && deal.times_seen < 2) return false;
      return matchesSearch(deal, query);
    }}));

    els.grid.innerHTML = rows.map(cardHtml).join('');
    els.empty.style.display = rows.length ? 'none' : 'block';
    els.statCount.textContent = rows.length.toLocaleString();
    els.statTotal.textContent = money(rows.reduce((sum, deal) => sum + deal.savings, 0));
    els.statTop.textContent = money(rows[0]?.savings || 0);
  }}

  function resetFilters() {{
    els.search.value = '';
    els.category.value = 'All';
    els.merchant.value = 'All';
    els.minSaving.value = '0';
    els.minSeen.value = '0';
    els.sort.value = 'savings-desc';
    els.emailedOnly.checked = false;
    els.repeatOnly.checked = false;
    applyFilters();
  }}

  els.toggle.addEventListener('click', () => {{
    const hidden = els.panel.toggleAttribute('hidden');
    els.toggle.setAttribute('aria-expanded', String(!hidden));
  }});
  els.reset.addEventListener('click', resetFilters);
  for (const el of [els.search, els.category, els.merchant, els.minSaving, els.minSeen, els.sort, els.emailedOnly, els.repeatOnly]) {{
    el.addEventListener('input', applyFilters);
    el.addEventListener('change', applyFilters);
  }}
  applyFilters();
</script>
"""


def build(memory_file: Path = MEMORY_FILE, output_file: Path = OUTPUT_FILE) -> tuple[int, Path]:
    deals, generated_at = load_all_memory_deals(memory_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(render_jekyll_html(deals, generated_at))
    return len(deals), output_file


def build_from_deals(deals: list[dict], output_file: Path = OUTPUT_FILE) -> tuple[int, Path]:
    rows, generated_at = deals_from_monitor_run(deals)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(render_jekyll_html(rows, generated_at))
    return len(rows), output_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", type=Path, default=MEMORY_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()
    count, output = build(args.memory, args.output)
    print(f"Built {output} with {count} deals")


if __name__ == "__main__":
    main()
