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


def load_latest_deals(memory_file: Path = MEMORY_FILE) -> tuple[list[dict], datetime]:
    payload = json.loads(memory_file.read_text())
    rows = []
    for item in payload.get("deals", {}).values():
        emailed_at = _parse_dt(item.get("last_emailed_at", ""))
        if emailed_at == datetime.min.replace(tzinfo=timezone.utc):
            continue
        rows.append({
            "title": item.get("last_title") or item.get("first_title") or "Untitled deal",
            "link": item.get("link") or "#",
            "node_id": item.get("node_id") or "",
            "savings": int(item.get("last_savings", 0) or 0),
            "best_savings": int(item.get("best_savings", 0) or 0),
            "times_seen": int(item.get("times_seen", 0) or 0),
            "email_count": int(item.get("email_count", 0) or 0),
            "last_emailed_at": emailed_at,
        })

    if not rows:
        return [], datetime.min.replace(tzinfo=timezone.utc)

    latest = max(row["last_emailed_at"] for row in rows)
    latest_rows = [row for row in rows if row["last_emailed_at"] == latest]
    latest_rows.sort(key=lambda row: row["savings"], reverse=True)
    for row in latest_rows:
        row["category"] = _category_from_title(row["title"])
        row["merchant"] = _merchant_from_title(row["title"])
    return latest_rows, latest


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


def build(memory_file: Path = MEMORY_FILE, output_file: Path = OUTPUT_FILE) -> tuple[int, Path]:
    deals, generated_at = load_latest_deals(memory_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(render_html(deals, generated_at))
    return len(deals), output_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", type=Path, default=MEMORY_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()
    count, output = build(args.memory, args.output)
    print(f"Built {output} with {count} deals")


if __name__ == "__main__":
    main()
