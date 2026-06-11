#!/usr/bin/env python3
"""Build a static deals website from the local OzBargain deal memory."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
MEMORY_FILE = ROOT / "outputs" / "deal_memory.json"
OUTPUT_FILE = ROOT / "docs" / "index.html"
SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def _money(value) -> str:
    try:
        return f"${int(value):,}"
    except (TypeError, ValueError):
        return "$0"


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _title_percent(title: str) -> float:
    match = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*%\s*(?:off|discount|saving|cashback)\b", title or "", re.IGNORECASE)
    if not match:
        return 0
    pct = _number(match.group(1))
    return pct if 0 < pct <= 95 else 0


def _title_market_price(title: str) -> int:
    match = re.search(r"\b(?:rrp|was|usually)\s*\$?\s*(\d[\d,]*(?:\.\d{1,2})?)\b", title or "", re.IGNORECASE)
    if not match:
        return 0
    value = _number(match.group(1).replace(",", ""))
    return int(value) if value > 0 else 0


def _title_deal_price(title: str) -> int:
    matches = re.finditer(r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)", title or "")
    for match in matches:
        prefix = (title[:match.start()] or "").lower()[-24:]
        if re.search(r"(rrp|was|usually|save|saving|cashback|bonus|valued|value|voucher|gift card)\s*$", prefix):
            continue
        value = _number(match.group(1).replace(",", ""))
        if value > 0:
            return int(value)
    return 0


def _savings_percent(deal: dict) -> float:
    title_pct = _title_percent(deal.get("title", ""))
    if title_pct:
        return title_pct
    market_price = int(deal.get("market_price", 0) or 0) or _title_market_price(deal.get("title", ""))
    savings = int(deal.get("savings", 0) or 0)
    if market_price > 0 and 0 < savings < market_price:
        return round((savings / market_price) * 100, 1)
    return 0


def _savings_percent_label(deal: dict) -> str:
    pct = _savings_percent(deal)
    if pct <= 0:
        return ""
    return f"{pct:.0f}% off" if pct >= 10 else f"{pct:.1f}% off"


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
    market_price = int(item.get("market_price", 0) or 0) or _title_market_price(title)
    deal_price = int(item.get("deal_price", 0) or 0) or _title_deal_price(title)
    row = {
        "title": title,
        "link": item.get("link") or "#",
        "node_id": item.get("node_id") or "",
        "savings": int(item.get("last_savings", 0) or 0),
        "best_savings": int(item.get("best_savings", 0) or 0),
        "deal_price": deal_price,
        "market_price": market_price,
        "savings_percent": 0,
        "times_seen": int(item.get("times_seen", 0) or 0),
        "email_count": int(item.get("email_count", 0) or 0),
        "last_emailed_at": emailed_at,
        "last_seen_at": last_seen_at,
        "first_seen_at": first_seen_at,
        "category": _category_from_title(title),
        "merchant": _merchant_from_title(title),
    }
    row["savings_percent"] = _savings_percent(row)
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
        title = deal.get("title") or "Untitled deal"
        market_price = int(deal.get("market_price", 0) or 0) or _title_market_price(title)
        deal_price = int(deal.get("deal_price", 0) or 0) or _title_deal_price(title)
        row = {
            "title": title,
            "link": deal.get("link") or "#",
            "node_id": str(deal.get("node_id") or ""),
            "savings": int(deal.get("savings", 0) or 0),
            "best_savings": int(deal.get("best_savings") or deal.get("previous_best_savings") or deal.get("savings", 0) or 0),
            "deal_price": deal_price,
            "market_price": market_price,
            "savings_percent": 0,
            "times_seen": int(deal.get("times_seen", 0) or 0) + 1,
            "email_count": int(deal.get("email_count", 0) or 0) + 1,
            "last_emailed_at": generated_at,
            "category": _category_from_title(deal.get("title", "")),
            "merchant": deal.get("merchant_name") or _merchant_from_title(deal.get("title", "")),
        }
        row["savings_percent"] = _savings_percent(row)
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
    generated = generated_at.astimezone(SYDNEY_TZ).strftime("%d %b %Y, %I:%M %p %Z")

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
    .save .percent {{ color: var(--good); font-size: 13px; text-transform: none; }}
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
    <div class="wrap">Potential value is AI-derived from deal signals and should be verified before purchase. Built with Claude AI Code and OpenAI Codex.</div>
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
    pct = _savings_percent_label(deal)
    pct_html = f'<span class="percent">Save {escape(pct)}</span>' if pct else ""
    return f"""<article class="card" data-category="{escape(category, quote=True)}" data-search="{escape(search, quote=True)}">
  <div>
    <div class="rank">#{rank} · {escape(category)}</div>
    <a class="title" href="{escape(deal['link'], quote=True)}" target="_blank" rel="noopener">{escape(title)}</a>
    <div class="meta">{escape(merchant)} · OzBargain signal</div>
    <div class="pillrow">
      <span class="pill">Best {_money(deal['best_savings'])}</span>
      <span class="pill">Agent pick</span>
    </div>
  </div>
  <div class="save">{_money(deal['savings'])}{pct_html}<span>Approx saving</span></div>
</article>"""


def _deal_payload(deals: list[dict]) -> str:
    payload = []
    for deal in deals:
        payload.append({
            "title": deal["title"],
            "link": deal["link"],
            "savings": int(deal["savings"]),
            "best_savings": int(deal["best_savings"]),
            "deal_price": int(deal.get("deal_price", 0) or 0),
            "market_price": int(deal.get("market_price", 0) or 0),
            "savings_percent": round(_savings_percent(deal), 1),
            "last_emailed_at": deal["last_emailed_at"].isoformat(),
            "last_seen_at": deal.get("last_seen_at", deal["last_emailed_at"]).isoformat(),
            "first_seen_at": deal.get("first_seen_at", deal["last_emailed_at"]).isoformat(),
            "category": deal["category"],
            "merchant": deal["merchant"],
        })
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def render_jekyll_html(deals: list[dict], generated_at: datetime) -> str:
    total = sum(d["savings"] for d in deals)
    top = deals[0]["savings"] if deals else 0
    categories = sorted({d["category"] for d in deals})
    merchants = sorted({d["merchant"] for d in deals})
    generated = generated_at.astimezone(SYDNEY_TZ).strftime("%d %b %Y, %I:%M %p %Z")
    category_options = "\n".join(f'<option value="{escape(category, quote=True)}">{escape(category)}</option>' for category in categories)
    merchant_options = "\n".join(f'<option value="{escape(merchant, quote=True)}">{escape(merchant)}</option>' for merchant in merchants)
    deal_json = _deal_payload(deals)

    return f"""---
layout: default
title: Today's best quantified deals
---
<div class="deal-radar">
  <header class="brand-header">
    <div>
      <div class="brand-kicker">AI-powered OzBargain monitor</div>
      <h1>OZB Deal Radar</h1>
      <p>Ranked deal intelligence with potential savings, urgency signals, and quick filters for the latest monitor run.</p>
    </div>
    <div class="brand-mark">OZB</div>
  </header>
  <section class="radar-intro">
    <div class="summary-head">
      <div>
        <div class="stamp">Latest run: {escape(generated)}</div>
        <p>Every remembered deal, ranked by potential value. Use quick views or open filters when you want to narrow the list.</p>
      </div>
    </div>
    <div class="stats">
      <div class="stat"><div class="label">Matching Deals</div><div class="value" id="stat-count">{len(deals)}</div></div>
      <div class="stat"><div class="label">Potential Value</div><div class="value" id="stat-total">{_money(total)}</div></div>
      <div class="stat"><div class="label">Top Saving</div><div class="value" id="stat-top">{_money(top)}</div></div>
    </div>
  </section>
  <section class="top-strip urgent-strip" id="urgent-strip" aria-label="Flash and time-sensitive deals"></section>
  <section class="preset-bar" aria-label="Saved preference presets">
    <button type="button" class="preset" data-preset="high">High savings</button>
    <button type="button" class="preset" data-preset="tech">Tech deals</button>
    <button type="button" class="preset" data-preset="home">Home deals</button>
    <button type="button" class="preset" data-preset="finance">Finance/cashback</button>
    <button type="button" class="preset" data-preset="watchlist">My watchlist</button>
  </section>
  <section class="category-summary" id="category-summary" aria-label="Category summary"></section>
  <div class="toolbar">
    <input id="search" placeholder="Search deals, merchants, categories" aria-label="Search deals">
    <button class="clear-filters" id="clear-filters" type="button">Reset</button>
    <button class="filter-toggle" id="filter-toggle" type="button" aria-expanded="false" aria-controls="filter-panel">Filters</button>
  </div>
  <section class="filter-panel" id="filter-panel" hidden>
    <label>
      Category
      <select id="category">
        <option value="All">All categories</option>
        {category_options}
      </select>
    </label>
    <label>
      Merchant
      <input id="merchant" list="merchant-list" placeholder="All merchants" aria-label="Merchant filter">
      <datalist id="merchant-list">
        {merchant_options}
      </datalist>
    </label>
    <label>
      Minimum saving
      <input id="min-saving" type="number" min="0" step="50" value="0">
    </label>
    <label>
      Sort
      <select id="sort">
        <option value="savings-desc">Savings high to low</option>
        <option value="best-desc">Best benchmark high to low</option>
        <option value="confidence-desc">AI confidence high to low</option>
        <option value="urgency-desc">Urgency high to low</option>
        <option value="recent-desc">Most recent</option>
      </select>
    </label>
    <label class="wide">
      Watchlist terms
      <input id="watchlist" placeholder="TV, Dyson, iPhone, travel, solar">
    </label>
    <div class="checks">
      <label><input id="agent-picks-only" type="checkbox"> Agent picks only</label>
      <label><input id="urgent-only" type="checkbox"> Urgent signals only</label>
      <label><input id="hide-expired" type="checkbox" checked> Hide expired/OOS</label>
    </div>
    <button class="reset" id="reset-filters" type="button">Reset</button>
  </section>
  <section class="chat-panel" id="deal-chat" aria-label="Deal assistant">
    <div class="chat-head">
      <div>
        <div class="chat-title">Deal Assistant</div>
        <div class="chat-subtitle">Ask the agent about value, urgency, categories, merchants, or risk signals.</div>
      </div>
      <button class="chat-clear" id="chat-clear" type="button">Clear</button>
    </div>
    <div class="chat-suggestions" aria-label="Suggested questions">
      <button type="button" data-chat-prompt="What are the best deals right now?">Best now</button>
      <button type="button" data-chat-prompt="Show urgent deals">Urgent</button>
      <button type="button" data-chat-prompt="Which deals have cashback or voucher risk?">Cashback risk</button>
      <button type="button" data-chat-prompt="Find TV and electronics deals">Electronics</button>
    </div>
    <div class="chat-log" id="chat-log" aria-live="polite"></div>
    <form class="chat-form" id="chat-form">
      <input id="chat-input" autocomplete="off" placeholder="Ask: best laptop deals, urgent finance offers, explain top deal..." aria-label="Ask the deal assistant">
      <button type="submit">Ask</button>
    </form>
  </section>
  <section class="top-strip" id="top-strip" aria-label="Top 10 deals"></section>
  <section class="grid" id="deals">
  </section>
  <div class="empty" id="empty">No matching deals.</div>
  <aside class="detail-drawer" id="detail-drawer" hidden aria-live="polite">
    <button class="drawer-close" id="drawer-close" type="button" aria-label="Close deal details">Close</button>
    <div id="drawer-content"></div>
  </aside>
  <p class="fineprint">Potential value is AI-derived from deal signals and should be verified before purchase. Built with Claude AI Code and OpenAI Codex.</p>
</div>
<script id="deal-data" type="application/json">{deal_json}</script>
<script>
  const deals = JSON.parse(document.querySelector('#deal-data').textContent);
  const els = {{
    search: document.querySelector('#search'),
    category: document.querySelector('#category'),
    merchant: document.querySelector('#merchant'),
    minSaving: document.querySelector('#min-saving'),
    sort: document.querySelector('#sort'),
    watchlist: document.querySelector('#watchlist'),
    agentPicksOnly: document.querySelector('#agent-picks-only'),
    urgentOnly: document.querySelector('#urgent-only'),
    hideExpired: document.querySelector('#hide-expired'),
    resetButtons: Array.from(document.querySelectorAll('#reset-filters, #clear-filters')),
    toggle: document.querySelector('#filter-toggle'),
    panel: document.querySelector('#filter-panel'),
    grid: document.querySelector('#deals'),
    urgentStrip: document.querySelector('#urgent-strip'),
    topStrip: document.querySelector('#top-strip'),
    categorySummary: document.querySelector('#category-summary'),
    drawer: document.querySelector('#detail-drawer'),
    drawerClose: document.querySelector('#drawer-close'),
    drawerContent: document.querySelector('#drawer-content'),
    empty: document.querySelector('#empty'),
    statCount: document.querySelector('#stat-count'),
    statTotal: document.querySelector('#stat-total'),
    statTop: document.querySelector('#stat-top'),
    chatLog: document.querySelector('#chat-log'),
    chatForm: document.querySelector('#chat-form'),
    chatInput: document.querySelector('#chat-input'),
    chatClear: document.querySelector('#chat-clear'),
  }};
  let currentRows = [];

  function money(value) {{
    return '$' + Math.round(value || 0).toLocaleString();
  }}

  function rawApproxPercent(deal) {{
    const explicit = Number(deal.savings_percent || 0);
    if (explicit > 0) return explicit;
    const savings = Number(deal.savings || 0);
    const market = Number(deal.market_price || 0);
    const dealPrice = Number(deal.deal_price || 0);
    const baseline = market > 0 ? market : (dealPrice > 0 ? dealPrice + savings : 0);
    if (savings > 0 && baseline > savings) return (savings / baseline) * 100;
    return 0;
  }}

  function percentLabel(deal) {{
    const explicit = Number(deal.savings_percent || 0);
    const pct = rawApproxPercent(deal);
    if (pct <= 0) return '';
    if (explicit > 0) return `~${{Math.round(pct)}}% saving`;
    const rounded = Math.max(1, Math.round(pct / 5) * 5);
    return `~${{rounded}}% saving`;
  }}

  function rrpLabel(deal) {{
    const market = Number(deal.market_price || 0);
    return market > 0 ? `RRP ${{money(market)}}` : '';
  }}

  function valueLine(deal) {{
    const parts = [];
    const pct = percentLabel(deal);
    const rrp = rrpLabel(deal);
    parts.push(pct || 'Approx saving');
    if (rrp) parts.push(rrp);
    if (!pct && !rrp && Number(deal.best_savings || 0) > Number(deal.savings || 0)) parts.push(`Best seen ${{money(deal.best_savings)}}`);
    return parts.join(' · ');
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

  function parseTerms(value) {{
    return String(value || '').split(',').map(term => term.trim().toLowerCase()).filter(Boolean);
  }}

  function dealText(deal) {{
    return [deal.title, deal.merchant, deal.category].join(' ').toLowerCase();
  }}

  function isExpired(deal) {{
    return /\\b(oos|expired|sold out|out of stock)\\b/i.test(deal.title || '');
  }}

  function daysSince(value) {{
    const ms = Date.now() - Date.parse(value || 0);
    if (!Number.isFinite(ms)) return 999;
    return Math.max(0, Math.floor(ms / 86400000));
  }}

  function qualityScore(deal) {{
    const savingScore = Math.min(45, Math.log10(Math.max(deal.savings, 1)) * 12);
    const bestScore = Math.min(15, Math.log10(Math.max(deal.best_savings, 1)) * 4);
    const freshScore = Math.max(0, 12 - daysSince(deal.last_seen_at) * 3);
    const penalty = isExpired(deal) ? 18 : 0;
    const signalScore = deal.best_savings && deal.savings >= deal.best_savings ? 8 : 0;
    return Math.max(1, Math.min(100, Math.round(savingScore + bestScore + freshScore + signalScore + 14 - penalty)));
  }}

  function aiConfidence(deal) {{
    let score = 46;
    if (deal.savings >= 1000) score += 18;
    else if (deal.savings >= 500) score += 12;
    else if (deal.savings >= 200) score += 8;
    if (deal.best_savings && deal.savings >= deal.best_savings) score += 10;
    if (daysSince(deal.last_seen_at) <= 1) score += 10;
    if (deal.merchant && deal.merchant !== 'OzBargain') score += 6;
    if (isTimeSensitive(deal)) score += 5;
    if (isExpired(deal)) score -= 28;
    return Math.max(1, Math.min(99, Math.round(score)));
  }}

  function urgencyScore(deal) {{
    let score = 20;
    if (isTimeSensitive(deal)) score += 35;
    if (daysSince(deal.first_seen_at) <= 1) score += 18;
    if (daysSince(deal.last_seen_at) <= 1) score += 10;
    if (deal.savings >= 1000) score += 10;
    if (/\\b(limited|clearance|ends|today|cashback|code|coupon|bonus)\\b/i.test(deal.title || '')) score += 12;
    if (isExpired(deal)) score = 5;
    return Math.max(1, Math.min(99, Math.round(score)));
  }}

  function valueSignal(deal) {{
    if (deal.savings >= 3000) return 'Exceptional value';
    if (deal.savings >= 1000) return 'High-value lead';
    if (deal.savings >= 500) return 'Strong saving';
    return 'Worth checking';
  }}

  function agentAction(deal) {{
    if (isExpired(deal)) return 'Skip or verify stock';
    if (urgencyScore(deal) >= 75 && aiConfidence(deal) >= 75) return 'Review now';
    if (aiConfidence(deal) >= 80) return 'Shortlist';
    if (urgencyScore(deal) >= 70) return 'Check window';
    return 'Monitor';
  }}

  function riskSignal(deal) {{
    const title = String(deal.title || '').toLowerCase();
    if (isExpired(deal)) return 'Availability risk';
    if (/\\b(cashback|rebate|voucher|gift card|points|refinance|loan|insurance)\\b/.test(title)) return 'Terms dependent';
    if (/\\b(code|coupon|limited|clearance|while stocks last)\\b/.test(title)) return 'Stock/window risk';
    if (deal.savings >= 1000) return 'Verify price';
    return 'Low friction';
  }}

  function agentInsight(deal) {{
    return `${{valueSignal(deal)}} · ${{riskSignal(deal)}} · ${{timeSensitiveReason(deal) || 'Stable window'}}`;
  }}

  function freshnessBadges(deal) {{
    const badges = [];
    const seenDays = daysSince(deal.last_seen_at);
    const firstSeenDays = daysSince(deal.first_seen_at);
    if (isExpired(deal)) badges.push('Expired/OOS');
    if (firstSeenDays <= 1) badges.push('Fresh lead');
    if (deal.best_savings && deal.savings >= deal.best_savings) badges.push('Best detected');
    if (seenDays >= 7) badges.push('Stale');
    if (aiConfidence(deal) >= 80) badges.push('High confidence');
    if (urgencyScore(deal) >= 75) badges.push('Action window');
    return badges.length ? badges : ['Agent reviewed'];
  }}

  function timeSensitiveReason(deal) {{
    const title = String(deal.title || '').toLowerCase();
    if (/\\b(today only|ends today|today\\b|tonight|last day|final day)\\b/.test(title)) return 'Ends today';
    if (/\\b(ends|ending|expires|expiring|until|limited time|limited stock|while stocks last|clearance|flash|deal of the day|one day)\\b/.test(title)) return 'Time sensitive';
    if (/\\b(code|coupon|cashback|bonus|afterpay|shopback|cashrewards)\\b/.test(title)) return 'Promo window';
    if (daysSince(deal.first_seen_at) <= 1) return 'New today';
    if (daysSince(deal.last_seen_at) <= 1 && deal.savings >= 500) return 'Fresh high saving';
    return '';
  }}

  function isTimeSensitive(deal) {{
    return !isExpired(deal) && Boolean(timeSensitiveReason(deal));
  }}

  function matchesSearch(deal, query) {{
    if (!query) return true;
    return dealText(deal).includes(query);
  }}

  function rankDeals(rows) {{
    const sort = els.sort.value;
    const copy = [...rows];
    copy.sort((a, b) => {{
      if (sort === 'score-desc') return (qualityScore(b) - qualityScore(a)) || (b.savings - a.savings);
      if (sort === 'best-desc') return (b.best_savings - a.best_savings) || (b.savings - a.savings);
      if (sort === 'confidence-desc') return (aiConfidence(b) - aiConfidence(a)) || (b.savings - a.savings);
      if (sort === 'urgency-desc') return (urgencyScore(b) - urgencyScore(a)) || (b.savings - a.savings);
      if (sort === 'recent-desc') return Date.parse(b.last_seen_at) - Date.parse(a.last_seen_at);
      return (b.savings - a.savings) || (b.best_savings - a.best_savings);
    }});
    return copy;
  }}

  function cardHtml(deal, index) {{
    const badges = freshnessBadges(deal).map(badge => `<span class="badge">${{escapeHtml(badge)}}</span>`).join('');
    const score = qualityScore(deal);
    return `<article class="card">
      <div>
        <div class="rank">#${{index + 1}} · ${{escapeHtml(deal.category)}} · Agent Score ${{score}}/100</div>
        <a class="title" href="${{escapeHtml(deal.link)}}" target="_blank" rel="noopener">${{escapeHtml(deal.title)}}</a>
        <div class="meta">${{escapeHtml(deal.merchant)}} · OzBargain signal</div>
        <div class="badges">${{badges}}</div>
        <div class="pillrow">
          <span class="pill">AI confidence ${{aiConfidence(deal)}}%</span>
          <span class="pill">Urgency ${{urgencyScore(deal)}}%</span>
          <span class="pill">${{escapeHtml(agentAction(deal))}}</span>
        </div>
        <div class="agent-note">${{escapeHtml(agentInsight(deal))}}</div>
        <button class="details" type="button" data-index="${{index}}">Details</button>
      </div>
      <div class="save">${{money(deal.savings)}}<span>${{escapeHtml(valueLine(deal))}}</span></div>
    </article>`;
  }}

  function topStripHtml(rows) {{
    const top = [...rows].sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a))).slice(0, 10);
    if (!top.length) return '';
    return `<div class="strip-head"><div class="strip-title">Top 10 strongest opportunities</div><button type="button" class="link-button" data-preset="high">High savings view</button></div><div class="strip-row">${{top.map((deal, i) => `
      <button type="button" class="mini-deal" data-top-index="${{i}}">
        <span>#${{i + 1}} · AI ${{aiConfidence(deal)}}% · ${{escapeHtml(agentAction(deal))}}</span>
        <b>${{escapeHtml(deal.title)}}</b>
        <em><strong>${{money(deal.savings)}}</strong> ${{escapeHtml(valueLine(deal))}}</em>
      </button>`).join('')}}</div>`;
  }}

  function urgentStripHtml(rows) {{
    const urgent = [...rows].filter(isTimeSensitive).sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a))).slice(0, 8);
    if (!urgent.length) return '';
    return `<div class="strip-head"><div><div class="strip-title urgent-title">Flash / time-sensitive deals</div><div class="strip-subtitle">Fresh, limited, ending, code, or cashback deals sorted by savings</div></div></div><div class="strip-row">${{urgent.map((deal, i) => `
      <button type="button" class="mini-deal urgent-deal" data-urgent-index="${{i}}">
        <span>#${{i + 1}} · Urgency ${{urgencyScore(deal)}}% · ${{escapeHtml(timeSensitiveReason(deal))}}</span>
        <b>${{escapeHtml(deal.title)}}</b>
        <em><strong>${{money(deal.savings)}}</strong> ${{escapeHtml(valueLine(deal))}}</em>
      </button>`).join('')}}</div>`;
  }}

  function renderCategorySummary(rows) {{
    const counts = new Map();
    for (const deal of rows) counts.set(deal.category, (counts.get(deal.category) || 0) + 1);
    const items = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
    els.categorySummary.innerHTML = `<button type="button" class="cat-chip" data-category="All">All <span>${{rows.length}}</span></button>` + items.map(([category, count]) =>
      `<button type="button" class="cat-chip" data-category="${{escapeHtml(category)}}">${{escapeHtml(category)}} <span>${{count}}</span></button>`
    ).join('');
  }}

  function encodeState() {{
    const params = new URLSearchParams();
    if (els.search.value.trim()) params.set('q', els.search.value.trim());
    if (els.category.value !== 'All') params.set('category', els.category.value);
    if (els.merchant.value.trim()) params.set('merchant', els.merchant.value.trim());
    if (Number(els.minSaving.value || 0) > 0) params.set('min', els.minSaving.value);
    if (els.sort.value !== 'savings-desc') params.set('sort', els.sort.value);
    if (els.watchlist.value.trim()) params.set('watchlist', els.watchlist.value.trim());
    if (els.agentPicksOnly.checked) params.set('agent', '1');
    if (els.urgentOnly.checked) params.set('urgent', '1');
    if (!els.hideExpired.checked) params.set('expired', 'show');
    const next = `${{location.pathname}}${{params.toString() ? '?' + params.toString() : ''}}`;
    history.replaceState(null, '', next);
  }}

  function loadStateFromUrl() {{
    const params = new URLSearchParams(location.search);
    els.search.value = params.get('q') || '';
    els.category.value = params.get('category') || 'All';
    els.merchant.value = params.get('merchant') || '';
    els.minSaving.value = params.get('min') || '0';
    els.sort.value = params.get('sort') || 'savings-desc';
    els.watchlist.value = params.get('watchlist') || '';
    els.agentPicksOnly.checked = params.get('agent') === '1';
    els.urgentOnly.checked = params.get('urgent') === '1';
    els.hideExpired.checked = params.get('expired') !== 'show';
  }}

  function applyFilters() {{
    const query = els.search.value.trim().toLowerCase();
    const minSaving = Number(els.minSaving.value || 0);
    const merchantQuery = els.merchant.value.trim().toLowerCase();
    const watchTerms = parseTerms(els.watchlist.value);
    const rows = rankDeals(deals.filter(deal => {{
      if (els.category.value !== 'All' && deal.category !== els.category.value) return false;
      if (merchantQuery && !deal.merchant.toLowerCase().includes(merchantQuery)) return false;
      if (deal.savings < minSaving) return false;
      if (els.agentPicksOnly.checked && aiConfidence(deal) < 75) return false;
      if (els.urgentOnly.checked && !isTimeSensitive(deal)) return false;
      if (els.hideExpired.checked && isExpired(deal)) return false;
      if (watchTerms.length && !watchTerms.some(term => dealText(deal).includes(term))) return false;
      return matchesSearch(deal, query);
    }}));

    currentRows = rows;
    els.grid.innerHTML = rows.map(cardHtml).join('');
    els.urgentStrip.innerHTML = urgentStripHtml(rows);
    els.topStrip.innerHTML = topStripHtml(rows);
    renderCategorySummary(rows);
    els.empty.style.display = rows.length ? 'none' : 'block';
    els.statCount.textContent = rows.length.toLocaleString();
    els.statTotal.textContent = money(rows.reduce((sum, deal) => sum + deal.savings, 0));
    els.statTop.textContent = money(rows[0]?.savings || 0);
    encodeState();
  }}

  function resetFilters() {{
    els.search.value = '';
    els.category.value = 'All';
    els.merchant.value = '';
    els.minSaving.value = '0';
    els.sort.value = 'savings-desc';
    els.watchlist.value = '';
    els.agentPicksOnly.checked = false;
    els.urgentOnly.checked = false;
    els.hideExpired.checked = true;
    applyFilters();
  }}

  function applyPreset(name) {{
    resetFilters();
    if (name === 'high') {{
      els.minSaving.value = '1000';
      els.sort.value = 'score-desc';
    }}
    if (name === 'tech') {{
      els.watchlist.value = 'tv, samsung, iphone, ipad, laptop, monitor, gaming pc, headphones';
      els.sort.value = 'score-desc';
    }}
    if (name === 'home') {{
      els.category.value = 'Home';
      els.sort.value = 'score-desc';
    }}
    if (name === 'finance') {{
      els.category.value = 'Finance';
      els.watchlist.value = 'cashback, credit card, qantas, velocity, home loan';
    }}
    if (name === 'watchlist') {{
      els.watchlist.value = 'dyson, iphone, tv, travel, solar, gaming pc';
      els.sort.value = 'score-desc';
    }}
    applyFilters();
  }}

  function detailHtml(deal) {{
    const badges = freshnessBadges(deal).map(badge => `<span class="badge">${{escapeHtml(badge)}}</span>`).join('');
    return `<h2>${{escapeHtml(deal.title)}}</h2>
      <div class="drawer-save">${{money(deal.savings)}} ${{escapeHtml(valueLine(deal))}} · Agent Score ${{qualityScore(deal)}}/100</div>
      <div class="badges">${{badges}}</div>
      <dl>
        <dt>AI confidence</dt><dd>${{aiConfidence(deal)}}%</dd>
        <dt>Urgency</dt><dd>${{urgencyScore(deal)}}%</dd>
        <dt>Recommended action</dt><dd>${{escapeHtml(agentAction(deal))}}</dd>
        <dt>Agent read</dt><dd>${{escapeHtml(agentInsight(deal))}}</dd>
        <dt>Merchant</dt><dd>${{escapeHtml(deal.merchant)}}</dd>
        <dt>Category</dt><dd>${{escapeHtml(deal.category)}}</dd>
        <dt>Value benchmark</dt><dd>${{money(deal.best_savings)}} best detected saving</dd>
        <dt>First detected</dt><dd>${{new Date(deal.first_seen_at).toLocaleString()}}</dd>
        <dt>Last checked</dt><dd>${{new Date(deal.last_seen_at).toLocaleString()}}</dd>
      </dl>
      <a class="drawer-link" href="${{escapeHtml(deal.link)}}" target="_blank" rel="noopener">Open OzBargain deal</a>`;
  }}

  function openDetails(deal) {{
    els.drawerContent.innerHTML = detailHtml(deal);
    els.drawer.hidden = false;
  }}

  function dealSummaryLine(deal, index) {{
    return `${{index + 1}}. ${{deal.title}} — ${{money(deal.savings)}} ${{valueLine(deal)}}, AI ${{aiConfidence(deal)}}%, urgency ${{urgencyScore(deal)}}%, action: ${{agentAction(deal)}}.`;
  }}

  function chatRowsForPrompt(prompt) {{
    const text = prompt.toLowerCase();
    let rows = currentRows.length ? [...currentRows] : rankDeals(deals);
    const terms = parseTerms(text.replace(/\\b(best|top|show|find|deals|deal|urgent|right now|what are|which|with|about|please|me|risk|offers|offer|explain)\\b/g, ' '));
    if (/\\burgent|flash|time|ending|limited|today\\b/.test(text)) rows = rows.filter(isTimeSensitive);
    if (/\\bcashback|voucher|gift card|points|loan|finance|insurance|rebate\\b/.test(text)) {{
      rows = rows.filter(deal => /\\b(cashback|voucher|gift card|points|loan|finance|insurance|rebate|qantas|velocity)\\b/i.test(deal.title + ' ' + deal.category));
    }}
    if (/\\brisk|terms|verify|caution\\b/.test(text)) {{
      rows = rows.filter(deal => riskSignal(deal) !== 'Low friction');
    }}
    if (/\\bconfidence|ai pick|agent pick|shortlist\\b/.test(text)) rows = rows.filter(deal => aiConfidence(deal) >= 75);
    if (terms.length) {{
      const narrowed = rows.filter(deal => terms.some(term => dealText(deal).includes(term)));
      if (narrowed.length) rows = narrowed;
    }}
    if (/\\burgency|urgent|flash|time\\b/.test(text)) return rows.sort((a, b) => (urgencyScore(b) - urgencyScore(a)) || (b.savings - a.savings));
    if (/\\bconfidence|ai\\b/.test(text)) return rows.sort((a, b) => (aiConfidence(b) - aiConfidence(a)) || (b.savings - a.savings));
    return rows.sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a)));
  }}

  function assistantReply(prompt) {{
    const text = prompt.toLowerCase();
    const rows = chatRowsForPrompt(prompt).filter(deal => !isExpired(deal)).slice(0, 5);
    if (/\\bhello|hi|help|what can you do\\b/.test(text)) {{
      return 'I can rank current deals by savings, urgency, AI confidence, merchant, category, cashback or voucher risk, and explain why a deal is worth checking.';
    }}
    if (/\\bexplain|why|top deal|first deal\\b/.test(text)) {{
      const deal = rows[0] || currentRows[0] || deals[0];
      if (!deal) return 'I do not have any deal data loaded yet.';
      return `${{deal.title}} looks like ${{agentAction(deal).toLowerCase()}}: ${{money(deal.savings)}} potential value, ${{aiConfidence(deal)}}% AI confidence, ${{urgencyScore(deal)}}% urgency. Agent read: ${{agentInsight(deal)}}.`;
    }}
    if (!rows.length) return 'I could not find matching active deals for that question. Try a category, merchant, product type, or ask for urgent/high-confidence deals.';
    const intro = /\\brisk|terms|verify|caution\\b/.test(text)
      ? 'These are the deals I would verify carefully:'
      : /\\burgent|flash|time|ending|limited|today\\b/.test(text)
        ? 'These are the most time-sensitive deals I found:'
        : 'Here are the strongest matching deals:';
    return `${{intro}}\\n${{rows.map(dealSummaryLine).join('\\n')}}`;
  }}

  function addChatMessage(role, text) {{
    const message = document.createElement('div');
    message.className = `chat-message ${{role}}`;
    message.textContent = text;
    els.chatLog.append(message);
    els.chatLog.scrollTop = els.chatLog.scrollHeight;
  }}

  function askAssistant(prompt) {{
    const question = prompt.trim();
    if (!question) return;
    addChatMessage('user', question);
    addChatMessage('assistant', assistantReply(question));
    els.chatInput.value = '';
  }}

  els.toggle.addEventListener('click', () => {{
    const hidden = els.panel.toggleAttribute('hidden');
    els.toggle.setAttribute('aria-expanded', String(!hidden));
  }});
  els.resetButtons.forEach(button => button.addEventListener('click', resetFilters));
  els.drawerClose.addEventListener('click', () => els.drawer.hidden = true);
  document.querySelectorAll('.preset').forEach(button => {{
    button.addEventListener('click', () => applyPreset(button.dataset.preset));
  }});
  els.categorySummary.addEventListener('click', event => {{
    const button = event.target.closest('.cat-chip');
    if (!button) return;
    els.category.value = button.dataset.category || 'All';
    applyFilters();
  }});
  els.topStrip.addEventListener('click', event => {{
    const presetButton = event.target.closest('.link-button');
    if (!presetButton) return;
    applyPreset(presetButton.dataset.preset);
  }});
  els.urgentStrip.addEventListener('click', event => {{
    const button = event.target.closest('.mini-deal');
    if (!button) return;
    const urgent = [...currentRows].filter(isTimeSensitive).sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a)));
    openDetails(urgent[Number(button.dataset.urgentIndex)]);
  }});
  els.grid.addEventListener('click', event => {{
    const button = event.target.closest('.details');
    if (!button) return;
    openDetails(currentRows[Number(button.dataset.index)]);
  }});
  els.topStrip.addEventListener('click', event => {{
    const button = event.target.closest('.mini-deal');
    if (!button) return;
    const top = [...currentRows].sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a)));
    openDetails(top[Number(button.dataset.topIndex)]);
  }});
  els.chatForm.addEventListener('submit', event => {{
    event.preventDefault();
    askAssistant(els.chatInput.value);
  }});
  els.chatClear.addEventListener('click', () => {{
    els.chatLog.innerHTML = '';
    addChatMessage('assistant', 'Ask me for best deals, urgent offers, cashback risk, or a product/category you care about.');
  }});
  document.querySelectorAll('[data-chat-prompt]').forEach(button => {{
    button.addEventListener('click', () => askAssistant(button.dataset.chatPrompt || ''));
  }});
  for (const el of [els.search, els.category, els.merchant, els.minSaving, els.sort, els.watchlist, els.agentPicksOnly, els.urgentOnly, els.hideExpired]) {{
    el.addEventListener('input', applyFilters);
    el.addEventListener('change', applyFilters);
  }}
  const scoreOption = document.createElement('option');
  scoreOption.value = 'score-desc';
  scoreOption.textContent = 'Value score high to low';
  els.sort.prepend(scoreOption);
  loadStateFromUrl();
  applyFilters();
  addChatMessage('assistant', 'Ask me for best deals, urgent offers, cashback risk, or a product/category you care about.');
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
