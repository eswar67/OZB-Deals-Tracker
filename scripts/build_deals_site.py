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


OZB_CATEGORY_MAP = {
    "automotive": "Automotive",
    "computing": "Computing",
    "electrical & electronics": "Electronics",
    "electronics": "Electronics",
    "entertainment": "Entertainment",
    "financial": "Finance",
    "gaming": "Gaming",
    "groceries": "Groceries",
    "health & beauty": "Health",
    "home & garden": "Home",
    "internet": "Internet",
    "mobile": "Mobile",
    "pets": "Pets",
    "sport & outdoor": "Outdoor",
    "travel": "Travel",
    "toys & kids": "Baby & Kids",
}


CATEGORY_RULES = [
    ("Travel", ("flight", "airfare", "airline", "hotel", "accommodation", "cruise", "lounge", "luggage", "travel", "qantas", "velocity", "lifemiles", "krisflyer", "asia miles", "emirates", "cathay")),
    ("Finance", ("credit card", "debit card", "bank", "banking", "home loan", "mortgage", "refinance", "offset account", "savings account", "term deposit", "insurance", "hospital cover", "extras cover", "health cover", "smsf", "super ", "amex", "american express", "westpac", "anz black")),
    ("Business", ("pty ltd", "ptd. ltd", "limited company", "virtual office", "company setup", "establishment setup", "amazon business", "zeller", "payment terminal", "terminals", "abn required")),
    ("Gift Cards", ("gift card", "gift cards", "egift card", "egift cards", "edr dollars", "store credit", "voucher", "coupon prizes")),
    ("Utilities", ("agl", "energy locals", "electricity", "gas bill", "fuel card", "fuel cards", "home select plan")),
    ("Mobile", ("iphone", "galaxy", "pixel", "motorola", "moto ", "oppo", "xiaomi", "phone", "smartphone", "mobile plan", "sim card", "esim", "prepaid", "optus", "telstra", "5g")),
    ("Computing", ("laptop", "macbook", "notebook", "chromebook", "desktop", "gaming pc", "graphics card", "gpu", "cpu", "ram", "ssd", "hard drive", "nas", "router", "ubiquiti", "keyboard", "mouse", "monitor", "printer")),
    ("Electronics", ("tv", "television", "oled", "qled", "mini led", "soundbar", "subwoofer", "speaker", "hifi", "headphones", "earbuds", "airpods", "bose", "sony wh", "sennheiser", "camera", "gopro", "tablet", "ipad", "kindle", "projector", "telescope", "v mount battery", "power station", "anker solix", "uhf radio", "uniden")),
    ("Gaming", ("playstation", "ps5", "xbox", "nintendo", "switch", "steam", "gaming", "console", "logitech g", "racing wheel", "game pass", "lego")),
    ("Tools", ("mitre saw", "mechanic", "mechanics tool", "tool set", "spanner", "gearwrench", "makita", "battery charger", "power tools", "bunnings", "sydney tools", "stepladder", "ladder")),
    ("Smart Home", ("smart lock", "aqara", "ring spotlight", "spotlight cam", "security camera", "doorbell")),
    ("Home Appliances", ("vacuum", "dyson", "roomba", "robot vacuum", "dehumidifier", "dehumidifiers", "air purifier", "fridge", "freezer", "washing machine", "washer", "dryer", "dishwasher", "karcher", "spot cleaner", "coffee machine", "coffee grinder", "nespresso", "espresso", "air fryer", "cooktop", "cooktops", "multi cooker", "instant pot", "casserole pot", "stock pot", "fry pan", "steel pan", "microwave")),
    ("Home", ("furniture", "coffee table", "mattress", "bed", "sofa", "standing desk", "chair", "solar", "garden", "lawn mower", "mower", "automower", "pressure washer")),
    ("Outdoor", ("hiking", "camping", "tent", "cabana", "beach cabana", "sleeping bag", "backpack", "puffer jacket", "insulated jacket", "rain jacket", "columbia", "north face", "patagonia", "macpac", "kayak", "bike", "bicycle", "cycling", "fitness", "treadmill")),
    ("Automotive", ("driveaway", "suv", "ute", "vehicle", "ev charger", "dash cam", "tyres", "car battery", "byd", "tesla", "vw ", "volkswagen", "skoda", "chery", "sealion", "tayron")),
    ("Health", ("toothbrush", "sonicare", "oral-b", "shaver", "chemist", "pharmacy", "vitamin", "supplement", "skincare", "sunscreen", "massage", "cpap", "hospital", "oura ring")),
    ("Baby & Kids", ("uppababy", "pram", "stroller", "car seat", "child seat", "baby", "toddler", "kids", "toy", "toys")),
    ("Fashion", ("watch", "watches", "footwear", "shoe", "shoes", "sneaker", "sneakers", "adidas", "allbirds", "saucony", "the iconic", "athlete's foot", "jacket", "jackets", "menswear", "shirts", "boots", "clothing", "apparel", "pants", "dress", "sunglasses")),
    ("Groceries", ("grocery", "groceries", "woolworths", "coles", "aldi", "costco", "wine", "wines", "cabernet", "sauvignon", "shiraz", "beer", "coffee beans", "chocolate", "nappies")),
    ("Entertainment", ("movie", "cinema", "streaming", "subscription", "audible", "spotify", "netflix", "disney+", "book", "star wars", "electronic helmet")),
    ("Pets", ("pet", "dog", "cat", "kibble", "petstock", "petbarn")),
    ("Internet", ("nbn", "broadband", "internet plan", "mobile broadband")),
    ("Shopping", ("referee", "referrer", "first purchase", "next purchase")),
]


CATEGORY_SEARCH_TERMS = {
    category: " ".join(words)
    for category, words in CATEGORY_RULES
}


def _contains_term(text: str, term: str) -> bool:
    if term.endswith(" "):
        return term in text
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def _category_from_signals(title: str, raw_categories: list[str] | None = None, merchant: str = "") -> str:
    for raw in raw_categories or []:
        mapped = OZB_CATEGORY_MAP.get(str(raw).strip().lower())
        if mapped:
            return mapped

    text = f"{title} {merchant}".lower()
    for category, terms in CATEGORY_RULES:
        if any(_contains_term(text, term) for term in terms):
            return category
    return "Other"


def _merchant_from_title(title: str) -> str:
    match = re.search(r"\s@\s*(.+)$", title)
    return match.group(1).strip() if match else "OzBargain"


def _row_from_memory_item(item: dict) -> dict:
    title = item.get("last_title") or item.get("first_title") or "Untitled deal"
    merchant = _merchant_from_title(title)
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
        "is_today_delta": False,
        "delta_reason": "",
        "last_emailed_at": emailed_at,
        "last_seen_at": last_seen_at,
        "first_seen_at": first_seen_at,
        "category": _category_from_signals(title, item.get("categories") or [], merchant),
        "merchant": merchant,
    }
    row["lowest_price_seen"] = int(item.get("lowest_price_seen", 0) or 0)
    history = item.get("price_history", []) or []
    if not row["lowest_price_seen"] and history:
        prices = [int(h.get("deal_price", 0) or 0) for h in history if int(h.get("deal_price", 0) or 0) > 0]
        row["lowest_price_seen"] = min(prices) if prices else 0
    row["is_lowest_price"] = bool(deal_price > 0 and row["lowest_price_seen"] and deal_price <= row["lowest_price_seen"])
    row["market_cheaper"] = bool(item.get("market_cheaper"))
    row["market_saving"] = int(item.get("market_saving", 0) or 0)
    row["cashback_platform"] = item.get("cashback_platform", "") or ""
    row["price_beat_count"] = len(item.get("price_beat_stores", []) or [])
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
        merchant = deal.get("merchant_name") or _merchant_from_title(title)
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
            "is_today_delta": bool(deal.get("is_new_deal") or deal.get("is_best_seen")),
            "delta_reason": ("new" if deal.get("is_new_deal") else ("saving_improved" if deal.get("is_best_seen") else "")),
            "last_emailed_at": generated_at,
            "category": _category_from_signals(title, deal.get("categories") or [], merchant),
            "merchant": merchant,
        }
        row["lowest_price_seen"] = int(deal.get("lowest_price_seen", 0) or 0)
        row["is_lowest_price"] = bool(deal.get("is_lowest_price"))
        row["market_cheaper"] = bool(deal.get("market_cheaper"))
        row["market_saving"] = int(deal.get("market_saving", 0) or 0)
        row["cashback_platform"] = deal.get("cashback_platform", "") or ""
        row["price_beat_count"] = len(deal.get("price_beat_stores", []) or [])
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
  <div class="save">{_money(deal['savings'])}<span>Potential saving</span></div>
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
            "is_today_delta": bool(deal.get("is_today_delta")),
            "delta_reason": deal.get("delta_reason", ""),
            "last_emailed_at": deal["last_emailed_at"].isoformat(),
            "last_seen_at": deal.get("last_seen_at", deal["last_emailed_at"]).isoformat(),
            "first_seen_at": deal.get("first_seen_at", deal["last_emailed_at"]).isoformat(),
            "category": deal["category"],
            "merchant": deal["merchant"],
            "search_terms": " ".join(
                part for part in [
                    deal["title"],
                    deal["merchant"],
                    deal["category"],
                    CATEGORY_SEARCH_TERMS.get(deal["category"], ""),
                ] if part
            ),
            "times_seen": int(deal.get("times_seen", 0) or 0),
            "lowest_price": int(deal.get("lowest_price_seen", 0) or 0),
            "is_lowest_price": bool(deal.get("is_lowest_price")),
            "market_cheaper": bool(deal.get("market_cheaper")),
            "market_saving": int(deal.get("market_saving", 0) or 0),
            "cashback_platform": deal.get("cashback_platform", "") or "",
            "price_beat_count": int(deal.get("price_beat_count", 0) or 0),
        })
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def _load_agent_config() -> dict:
    """Config for the Deal Assistant agent: points valuations, goal maps,
    and an optional LLM proxy endpoint (set agent_llm_endpoint in user-prefs.json
    to enable a real generative brain via a serverless proxy)."""
    try:
        prefs = json.loads((ROOT / "user-prefs.json").read_text())
    except Exception:
        prefs = {}
    points_raw = prefs.get("points_value_per_point_aud", {}) or {}
    points = {k: v for k, v in points_raw.items() if isinstance(v, (int, float))}
    points.setdefault("default", 0.01)
    # Program aliases → canonical key used in `points`
    aliases = {
        "qantas": "qantas", "qff": "qantas", "qantas points": "qantas",
        "velocity": "velocity", "virgin": "velocity", "velocity points": "velocity",
        "amex": "amex_mrp", "membership rewards": "amex_mrp", "mr": "amex_mrp", "amex mr": "amex_mrp",
        "lifemiles": "lifemiles", "avianca": "lifemiles",
        "asia miles": "asia_miles", "cathay": "asia_miles",
        "krisflyer": "krisflyer", "singapore airlines": "krisflyer", "kris flyer": "krisflyer",
    }
    goals = {
        "travel": ["flight", "hotel", "airline", "cruise", "lounge", "travel", "luggage", "accommodation"],
        "points": ["qantas", "velocity", "points", "frequent flyer", "transfer bonus", "amex", "membership rewards", "status"],
        "tech": ["tv", "laptop", "macbook", "iphone", "ipad", "monitor", "headphones", "ssd", "gaming pc", "console"],
        "home": ["vacuum", "dyson", "fridge", "appliance", "coffee", "espresso", "air fryer", "mattress", "furniture", "robot"],
        "finance": ["cashback", "credit card", "loan", "insurance", "refinance", "offset", "home loan", "savings account"],
    }
    return {
        "points": points,
        "point_aliases": aliases,
        "goals": goals,
        "llm_endpoint": prefs.get("agent_llm_endpoint", "") or "",
    }


def _load_latest_audit() -> dict:
    """Best-effort load of the most recent missed-deal audit (written by deal_memory)."""
    try:
        return json.loads((ROOT / "outputs" / "latest_missed_deal_audit.json").read_text())
    except Exception:
        return {}


def _render_near_miss(audit: dict) -> str:
    """Server-rendered 'near misses' block: relevant deals dropped just under threshold."""
    if not audit:
        return ""
    dropped = audit.get("top_dropped", []) or []
    near = [
        d for d in dropped
        if d.get("reason") == "below_savings_threshold" and int(d.get("savings", 0) or 0) > 0
    ]
    near.sort(key=lambda d: int(d.get("savings", 0) or 0), reverse=True)
    near = near[:8]
    if not near:
        return ""
    min_sav = int(audit.get("min_savings", 0) or 0)
    rows = ""
    for d in near:
        title = escape(d.get("title", "") or "Untitled")
        link = escape(d.get("link", "#") or "#", quote=True)
        merch = escape(d.get("merchant", "") or "")
        sav = _money(d.get("savings", 0))
        rows += (
            f'<a class="near-row" href="{link}" target="_blank" rel="noopener">'
            f'<span class="near-title">{title}</span>'
            f'<span class="near-meta">{merch}</span>'
            f'<span class="near-save">{sav}</span></a>'
        )
    hint = (
        f"{len(near)} relevant deals landed just under your ${min_sav:,} savings floor this run. "
        f"Lower the threshold in user-prefs.json to surface deals like these."
    )
    return (
        '<details class="deal-section near-miss-section">'
        '<summary><span>Near misses</span><strong>' + str(len(near)) + '</strong></summary>'
        '<div class="section-subtitle">' + escape(hint) + '</div>'
        '<div class="near-list">' + rows + '</div>'
        '</details>'
    )


def render_jekyll_html(deals: list[dict], generated_at: datetime) -> str:
    total = sum(d["savings"] for d in deals)
    top = max((d["savings"] for d in deals), default=0)
    delta_deals = [d for d in deals if d.get("is_today_delta")]
    delta_total = sum(d["savings"] for d in delta_deals)
    delta_top = max((d["savings"] for d in delta_deals), default=0)
    active_avg = round(total / len(deals)) if deals else 0
    categories = sorted({d["category"] for d in deals})
    merchants = sorted({d["merchant"] for d in deals})
    generated = generated_at.astimezone(SYDNEY_TZ).strftime("%d %b %Y, %I:%M %p %Z")
    category_options = "\n".join(f'<option value="{escape(category, quote=True)}">{escape(category)}</option>' for category in categories)
    merchant_options = "\n".join(f'<option value="{escape(merchant, quote=True)}">{escape(merchant)}</option>' for merchant in merchants)
    deal_json = _deal_payload(deals)
    agent_config_json = json.dumps(_load_agent_config(), ensure_ascii=False).replace("</", "<\\/")
    near_miss_html = _render_near_miss(_load_latest_audit())

    head = f"""---
layout: default
title: Today's best quantified deals
---
<div class="deal-radar">

  <header class="brand-header">
    <div class="brand-id">
      <div class="brand-mark">OZB</div>
      <div class="brand-text">
        <div class="brand-kicker">AI-powered OzBargain monitor</div>
        <h1>Deal Radar</h1>
      </div>
    </div>
    <p class="brand-lede">Ranked deal intelligence with quantified savings, urgency signals, and live agent scoring for the latest monitor run.</p>
    <div class="stamp">Latest run: {escape(generated)}</div>
  </header>

  <section class="metric-band" aria-label="Today's deals summary">
    <div class="metric metric-hero">
      <div class="metric-label">Top deal today</div>
      <div class="metric-value" id="stat-today-top">{_money(delta_top)}</div>
    </div>
    <div class="metric-divider" aria-hidden="true"></div>
    <div class="metric">
      <div class="metric-label">Today's deals</div>
      <div class="metric-value" id="stat-delta">{len(delta_deals)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Today's value</div>
      <div class="metric-value" id="stat-delta-total">{_money(delta_total)}</div>
    </div>
  </section>

  <section class="urgent-strip" id="urgent-strip" aria-label="Flash and time-sensitive deals"></section>

  <div class="control-rail">
    <div class="toolbar">
      <input id="search" placeholder="Search deals, merchants, categories" aria-label="Search deals">
      <button class="clear-filters" id="clear-filters" type="button">Reset</button>
      <button class="filter-toggle" id="filter-toggle" type="button" aria-expanded="false" aria-controls="filter-panel">Filters</button>
    </div>
    <section class="preset-bar" aria-label="Saved preference presets">
      <button type="button" class="preset" data-preset="high">High savings</button>
      <button type="button" class="preset" data-preset="tech">Tech deals</button>
      <button type="button" class="preset" data-preset="home">Home deals</button>
      <button type="button" class="preset" data-preset="finance">Finance/cashback</button>
      <button type="button" class="preset" data-preset="watchlist">My watchlist</button>
    </section>
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

  <section class="category-summary" id="category-summary" aria-label="Category summary"></section>

  <div class="deals-column">
    <section class="top-strip" id="top-strip" aria-label="Top 10 delta deals"></section>
    <section class="deal-section today-section">
      <div class="section-head">
        <div>
          <div class="section-title">Today's delta deals</div>
          <div class="section-subtitle">New, first-time, or improved deals from this run.</div>
        </div>
        <div class="section-count" id="today-count">{len(delta_deals)}</div>
      </div>
      <section class="grid" id="today-deals"></section>
      <div class="empty" id="today-empty">No new or improved deals match the current filters.</div>
    </section>
    <details class="deal-section all-active-section" id="all-active-details">
      <summary>
        <span>All active deals</span>
        <strong id="all-count">{len(deals)}</strong>
      </summary>
      <section class="metric-band active-band" aria-label="Active deals statistics">
        <div class="metric metric-hero">
          <div class="metric-label">Top active saving</div>
          <div class="metric-value" id="stat-top">{_money(top)}</div>
        </div>
        <div class="metric-divider" aria-hidden="true"></div>
        <div class="metric">
          <div class="metric-label">Active deals</div>
          <div class="metric-value" id="stat-count">{len(deals)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Active value</div>
          <div class="metric-value" id="stat-total">{_money(total)}</div>
        </div>
        <div class="metric">
          <div class="metric-label">Avg saving</div>
          <div class="metric-value" id="stat-active-avg">{_money(active_avg)}</div>
        </div>
      </section>
      <div class="section-subtitle">Full current active list, still sorted by savings and controlled by the filters above.</div>
      <section class="grid" id="deals"></section>
      <div class="empty" id="empty">No active deals match the current filters.</div>
    </details>
    {near_miss_html}
  </div>

  <aside class="detail-drawer" id="detail-drawer" hidden aria-live="polite">
    <button class="drawer-close" id="drawer-close" type="button" aria-label="Close deal details">Close</button>
    <div id="drawer-content"></div>
  </aside>

  <p class="fineprint">Potential value is AI-derived from deal signals and should be verified before purchase. Built with Claude AI Code and OpenAI Codex.</p>

  <button class="chat-fab" id="chat-fab" type="button" aria-label="Open Deal Assistant" aria-expanded="false">
    <span class="fab-glyph fab-open" aria-hidden="true">&#9670;</span>
    <span class="fab-glyph fab-close" aria-hidden="true">&times;</span>
    <span class="fab-ring" aria-hidden="true"></span>
  </button>

  <div class="chat-dock" id="chat-dock" hidden>
    <section class="chat-panel" id="deal-chat" aria-label="Deal assistant">
      <div class="chat-head">
        <div>
          <div class="chat-title"><span class="chat-pulse" aria-hidden="true"></span>Deal Assistant</div>
          <div class="chat-subtitle">Ask about value, urgency, categories, merchants, or risk.</div>
        </div>
        <button class="chat-dock-close" id="chat-dock-close" type="button" aria-label="Close assistant">&times;</button>
      </div>
      <div class="chat-suggestions" aria-label="Suggested questions">
        <button type="button" data-chat-prompt="Best tech deals under $1000">Tech under $1k</button>
        <button type="button" data-chat-prompt="How much is 250k Amex points worth?">Value 250k Amex</button>
        <button type="button" data-chat-prompt="Which deals are cheaper elsewhere?">Hype check</button>
        <button type="button" data-chat-prompt="Show cashback stacking deals">Cashback stack</button>
        <button type="button" data-chat-prompt="How many finance deals are there?">Aggregate</button>
      </div>
      <div class="chat-log" id="chat-log" aria-live="polite"></div>
      <form class="chat-form" id="chat-form">
        <input id="chat-input" autocomplete="off" placeholder="Ask: best laptop deals, urgent finance offers..." aria-label="Ask the deal assistant">
        <button type="submit">Ask</button>
      </form>
      <button class="chat-clear" id="chat-clear" type="button">Clear conversation</button>
    </section>
  </div>

</div>
<script id="deal-data" type="application/json">{deal_json}</script>
<script id="agent-config" type="application/json">{agent_config_json}</script>
"""

    script = SITE_SCRIPT
    return head + script


SITE_SCRIPT = r"""<script>
  const deals = JSON.parse(document.querySelector('#deal-data').textContent);
  const els = {
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
    todayGrid: document.querySelector('#today-deals'),
    grid: document.querySelector('#deals'),
    urgentStrip: document.querySelector('#urgent-strip'),
    topStrip: document.querySelector('#top-strip'),
    categorySummary: document.querySelector('#category-summary'),
    drawer: document.querySelector('#detail-drawer'),
    drawerClose: document.querySelector('#drawer-close'),
    drawerContent: document.querySelector('#drawer-content'),
    empty: document.querySelector('#empty'),
    todayEmpty: document.querySelector('#today-empty'),
    todayCount: document.querySelector('#today-count'),
    allCount: document.querySelector('#all-count'),
    statDelta: document.querySelector('#stat-delta'),
    statDeltaTotal: document.querySelector('#stat-delta-total'),
    statCount: document.querySelector('#stat-count'),
    statTotal: document.querySelector('#stat-total'),
    statTop: document.querySelector('#stat-top'),
    statTodayTop: document.querySelector('#stat-today-top'),
    statActiveAvg: document.querySelector('#stat-active-avg'),
    chatLog: document.querySelector('#chat-log'),
    chatForm: document.querySelector('#chat-form'),
    chatInput: document.querySelector('#chat-input'),
    chatClear: document.querySelector('#chat-clear'),
  };
  let currentRows = [];
  let currentTodayRows = [];
  let currentFocusRows = [];

  function money(value) {
    return '$' + Math.round(value || 0).toLocaleString();
  }

  function rrpLabel(deal) {
    const market = Number(deal.market_price || 0);
    return market > 0 ? `RRP ${money(market)}` : '';
  }

  function valueLine(deal) {
    const parts = ['Potential saving'];
    const rrp = rrpLabel(deal);
    if (rrp) parts.push(rrp);
    if (!rrp && Number(deal.best_savings || 0) > Number(deal.savings || 0)) parts.push(`Best seen ${money(deal.best_savings)}`);
    return parts.join(' · ');
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[char]));
  }

  function parseTerms(value) {
    return String(value || '').split(',').map(term => term.trim().toLowerCase()).filter(Boolean);
  }

  function dealText(deal) {
    return String(deal.search_terms || [deal.title, deal.merchant, deal.category].join(' ')).toLowerCase();
  }

  function dealTokens(deal) {
    return new Set(tokenize(dealText(deal)));
  }

  function isExpired(deal) {
    return /\b(oos|expired|sold out|out of stock)\b/i.test(deal.title || '');
  }

  function daysSince(value) {
    const ms = Date.now() - Date.parse(value || 0);
    if (!Number.isFinite(ms)) return 999;
    return Math.max(0, Math.floor(ms / 86400000));
  }

  function qualityScore(deal) {
    const savingScore = Math.min(45, Math.log10(Math.max(deal.savings, 1)) * 12);
    const bestScore = Math.min(15, Math.log10(Math.max(deal.best_savings, 1)) * 4);
    const freshScore = Math.max(0, 12 - daysSince(deal.last_seen_at) * 3);
    const penalty = isExpired(deal) ? 18 : 0;
    const signalScore = deal.best_savings && deal.savings >= deal.best_savings ? 8 : 0;
    return Math.max(1, Math.min(100, Math.round(savingScore + bestScore + freshScore + signalScore + 14 - penalty)));
  }

  function aiConfidence(deal) {
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
  }

  function urgencyScore(deal) {
    let score = 20;
    if (isTimeSensitive(deal)) score += 35;
    if (daysSince(deal.first_seen_at) <= 1) score += 18;
    if (daysSince(deal.last_seen_at) <= 1) score += 10;
    if (deal.savings >= 1000) score += 10;
    if (/\b(limited|clearance|ends|today|cashback|code|coupon|bonus)\b/i.test(deal.title || '')) score += 12;
    if (isExpired(deal)) score = 5;
    return Math.max(1, Math.min(99, Math.round(score)));
  }

  function valueSignal(deal) {
    if (deal.savings >= 3000) return 'Exceptional value';
    if (deal.savings >= 1000) return 'High-value lead';
    if (deal.savings >= 500) return 'Strong saving';
    return 'Worth checking';
  }

  function agentAction(deal) {
    if (isExpired(deal)) return 'Skip or verify stock';
    if (urgencyScore(deal) >= 75 && aiConfidence(deal) >= 75) return 'Review now';
    if (aiConfidence(deal) >= 80) return 'Shortlist';
    if (urgencyScore(deal) >= 70) return 'Check window';
    return 'Monitor';
  }

  function riskSignal(deal) {
    const title = String(deal.title || '').toLowerCase();
    if (isExpired(deal)) return 'Availability risk';
    if (/\b(cashback|rebate|voucher|gift card|points|refinance|loan|insurance)\b/.test(title)) return 'Terms dependent';
    if (/\b(code|coupon|limited|clearance|while stocks last)\b/.test(title)) return 'Stock/window risk';
    if (deal.savings >= 1000) return 'Verify price';
    return 'Low friction';
  }

  function agentInsight(deal) {
    return `${valueSignal(deal)} · ${riskSignal(deal)} · ${timeSensitiveReason(deal) || 'Stable window'}`;
  }

  function ledgerHtml(deal) {
    const items = [`<span class="ledger-item ledger-base">Base ${money(deal.savings)}</span>`];
    if (deal.cashback_platform) items.push(`<span class="ledger-item ledger-cash">+ ${escapeHtml(deal.cashback_platform)} cashback</span>`);
    if (Number(deal.price_beat_count) > 0) items.push(`<span class="ledger-item ledger-beat">Price-beat ${deal.price_beat_count} store${deal.price_beat_count > 1 ? 's' : ''}</span>`);
    if (Number(deal.lowest_price) > 0) {
      const label = deal.is_lowest_price ? 'Lowest tracked price' : `Lowest seen ${money(deal.lowest_price)}`;
      items.push(`<span class="ledger-item ledger-low${deal.is_lowest_price ? ' is-lowest' : ''}">${label}</span>`);
    }
    if (items.length <= 1) return '';
    return `<div class="ledger">${items.join('')}</div>`;
  }

  function hypeWarning(deal) {
    if (deal.market_cheaper && Number(deal.market_saving) < 0) {
      return `<div class="deal-warn">Market ~${money(Math.abs(deal.market_saving))} cheaper elsewhere — verify before buying</div>`;
    }
    return '';
  }

  function freshnessBadges(deal) {
    const badges = [];
    const seenDays = daysSince(deal.last_seen_at);
    const firstSeenDays = daysSince(deal.first_seen_at);
    if (isExpired(deal)) badges.push('Expired/OOS');
    if (firstSeenDays <= 1) badges.push('Fresh lead');
    if (deal.best_savings && deal.savings >= deal.best_savings) badges.push('Best detected');
    if (deal.is_today_delta) badges.push(deltaLabel(deal));
    if (deal.is_lowest_price) badges.push('Lowest price');
    if (seenDays >= 7) badges.push('Stale');
    if (aiConfidence(deal) >= 80) badges.push('High confidence');
    if (urgencyScore(deal) >= 75) badges.push('Action window');
    return badges.length ? badges : ['Agent reviewed'];
  }

  function deltaLabel(deal) {
    if (deal.delta_reason === 'saving_improved') return 'Improved today';
    if (deal.delta_reason === 'first_email') return 'First email';
    if (deal.delta_reason === 'new') return 'New today';
    return 'Today';
  }

  function timeSensitiveReason(deal) {
    const title = String(deal.title || '').toLowerCase();
    if (/\b(today only|ends today|today\b|tonight|last day|final day)\b/.test(title)) return 'Ends today';
    if (/\b(ends|ending|expires|expiring|until|limited time|limited stock|while stocks last|clearance|flash|deal of the day|one day)\b/.test(title)) return 'Time sensitive';
    if (/\b(code|coupon|cashback|bonus|afterpay|shopback|cashrewards)\b/.test(title)) return 'Promo window';
    if (daysSince(deal.first_seen_at) <= 1) return 'New today';
    if (daysSince(deal.last_seen_at) <= 1 && deal.savings >= 500) return 'Fresh high saving';
    return '';
  }

  function isTimeSensitive(deal) {
    return !isExpired(deal) && Boolean(timeSensitiveReason(deal));
  }

  function matchesSearch(deal, query) {
    if (!query) return true;
    return dealText(deal).includes(query);
  }

  function rankDeals(rows) {
    const sort = els.sort.value;
    const copy = [...rows];
    copy.sort((a, b) => {
      if (sort === 'score-desc') return (qualityScore(b) - qualityScore(a)) || (b.savings - a.savings);
      if (sort === 'best-desc') return (b.best_savings - a.best_savings) || (b.savings - a.savings);
      if (sort === 'confidence-desc') return (aiConfidence(b) - aiConfidence(a)) || (b.savings - a.savings);
      if (sort === 'urgency-desc') return (urgencyScore(b) - urgencyScore(a)) || (b.savings - a.savings);
      if (sort === 'recent-desc') return Date.parse(b.last_seen_at) - Date.parse(a.last_seen_at);
      return (b.savings - a.savings) || (b.best_savings - a.best_savings);
    });
    return copy;
  }

  function cardHtml(deal, index, scope = 'all') {
    const badges = freshnessBadges(deal).map(badge => `<span class="badge">${escapeHtml(badge)}</span>`).join('');
    const score = qualityScore(deal);
    return `<article class="card">
      <div>
        <div class="rank">#${index + 1} · ${escapeHtml(deal.category)} · Agent Score ${score}/100</div>
        <a class="title" href="${escapeHtml(deal.link)}" target="_blank" rel="noopener">${escapeHtml(deal.title)}</a>
        <div class="meta">${escapeHtml(deal.merchant)} · OzBargain signal</div>
        ${hypeWarning(deal)}
        <div class="badges">${badges}</div>
        <div class="pillrow">
          <span class="pill">AI confidence ${aiConfidence(deal)}%</span>
          <span class="pill">Urgency ${urgencyScore(deal)}%</span>
          <span class="pill">${escapeHtml(agentAction(deal))}</span>
        </div>
        ${ledgerHtml(deal)}
        <div class="agent-note">${escapeHtml(agentInsight(deal))}</div>
        <button class="details" type="button" data-scope="${scope}" data-index="${index}">Details</button>
      </div>
      <div class="save">${money(deal.savings)}<span>${escapeHtml(valueLine(deal))}</span></div>
    </article>`;
  }

  function topStripHtml(rows) {
    const top = [...rows].sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a))).slice(0, 10);
    if (!top.length) return '';
    return `<div class="strip-head"><div class="strip-title">Top 10 strongest opportunities</div><button type="button" class="link-button" data-preset="high">High savings view</button></div><div class="strip-row">${top.map((deal, i) => `
      <button type="button" class="mini-deal" data-top-index="${i}">
        <span>#${i + 1} · AI ${aiConfidence(deal)}% · ${escapeHtml(agentAction(deal))}</span>
        <b>${escapeHtml(deal.title)}</b>
        <em><strong>${money(deal.savings)}</strong> ${escapeHtml(valueLine(deal))}</em>
      </button>`).join('')}</div>`;
  }

  function urgentStripHtml(rows) {
    const urgent = [...rows].filter(isTimeSensitive).sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a))).slice(0, 8);
    if (!urgent.length) return '';
    return `<div class="strip-head"><div><div class="strip-title urgent-title">Flash / time-sensitive deals</div><div class="strip-subtitle">Fresh, limited, ending, code, or cashback deals sorted by savings</div></div></div><div class="strip-row">${urgent.map((deal, i) => `
      <button type="button" class="mini-deal urgent-deal" data-urgent-index="${i}">
        <span>#${i + 1} · Urgency ${urgencyScore(deal)}% · ${escapeHtml(timeSensitiveReason(deal))}</span>
        <b>${escapeHtml(deal.title)}</b>
        <em><strong>${money(deal.savings)}</strong> ${escapeHtml(valueLine(deal))}</em>
      </button>`).join('')}</div>`;
  }

  function renderCategorySummary(rows) {
    const counts = new Map();
    for (const deal of rows) counts.set(deal.category, (counts.get(deal.category) || 0) + 1);
    const items = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
    els.categorySummary.innerHTML = `<button type="button" class="cat-chip" data-category="All">All <span>${rows.length}</span></button>` + items.map(([category, count]) =>
      `<button type="button" class="cat-chip" data-category="${escapeHtml(category)}">${escapeHtml(category)} <span>${count}</span></button>`
    ).join('');
  }

  function encodeState() {
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
    const next = `${location.pathname}${params.toString() ? '?' + params.toString() : ''}`;
    history.replaceState(null, '', next);
  }

  function loadStateFromUrl() {
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
  }

  function applyFilters() {
    const query = els.search.value.trim().toLowerCase();
    const minSaving = Number(els.minSaving.value || 0);
    const merchantQuery = els.merchant.value.trim().toLowerCase();
    const watchTerms = parseTerms(els.watchlist.value);
    const rows = rankDeals(deals.filter(deal => {
      if (els.category.value !== 'All' && deal.category !== els.category.value) return false;
      if (merchantQuery && !deal.merchant.toLowerCase().includes(merchantQuery)) return false;
      if (deal.savings < minSaving) return false;
      if (els.agentPicksOnly.checked && aiConfidence(deal) < 75) return false;
      if (els.urgentOnly.checked && !isTimeSensitive(deal)) return false;
      if (els.hideExpired.checked && isExpired(deal)) return false;
      if (watchTerms.length && !watchTerms.some(term => dealText(deal).includes(term))) return false;
      return matchesSearch(deal, query);
    }));

    const todayRows = rows.filter(deal => deal.is_today_delta);
    const focusRows = todayRows.length ? todayRows : rows;

    currentRows = rows;
    currentTodayRows = todayRows;
    currentFocusRows = focusRows;
    els.todayGrid.innerHTML = todayRows.map((deal, index) => cardHtml(deal, index, 'today')).join('');
    els.grid.innerHTML = rows.map((deal, index) => cardHtml(deal, index, 'all')).join('');
    els.urgentStrip.innerHTML = urgentStripHtml(focusRows);
    els.topStrip.innerHTML = topStripHtml(focusRows);
    renderCategorySummary(rows);
    els.todayEmpty.style.display = todayRows.length ? 'none' : 'block';
    els.empty.style.display = rows.length ? 'none' : 'block';
    els.todayCount.textContent = todayRows.length.toLocaleString();
    els.allCount.textContent = rows.length.toLocaleString();
    const todaySavings = todayRows.reduce((sum, deal) => sum + deal.savings, 0);
    const activeSavings = rows.reduce((sum, deal) => sum + deal.savings, 0);
    // Top section — today's deals only
    els.statDelta.textContent = todayRows.length.toLocaleString();
    els.statDeltaTotal.textContent = money(todaySavings);
    els.statTodayTop.textContent = money(todayRows.length ? Math.max(...todayRows.map(deal => deal.savings)) : 0);
    // Active section — all active deals
    els.statCount.textContent = rows.length.toLocaleString();
    els.statTotal.textContent = money(activeSavings);
    els.statTop.textContent = money(rows.length ? Math.max(...rows.map(deal => deal.savings)) : 0);
    els.statActiveAvg.textContent = money(rows.length ? Math.round(activeSavings / rows.length) : 0);
    encodeState();
  }

  function resetFilters() {
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
  }

  function applyPreset(name) {
    resetFilters();
    if (name === 'high') {
      els.minSaving.value = '1000';
      els.sort.value = 'score-desc';
    }
    if (name === 'tech') {
      els.watchlist.value = 'tv, samsung, iphone, ipad, laptop, monitor, gaming pc, headphones';
      els.sort.value = 'score-desc';
    }
    if (name === 'home') {
      els.category.value = 'Home';
      els.sort.value = 'score-desc';
    }
    if (name === 'finance') {
      els.category.value = 'Finance';
      els.watchlist.value = 'cashback, credit card, qantas, velocity, home loan';
    }
    if (name === 'watchlist') {
      els.watchlist.value = 'dyson, iphone, tv, travel, solar, gaming pc';
      els.sort.value = 'score-desc';
    }
    applyFilters();
  }

  function detailHtml(deal) {
    const badges = freshnessBadges(deal).map(badge => `<span class="badge">${escapeHtml(badge)}</span>`).join('');
    const lowestRow = Number(deal.lowest_price) > 0
      ? `<dt>Lowest tracked</dt><dd>${money(deal.lowest_price)}${deal.is_lowest_price ? ' (current is lowest)' : ''}</dd>`
      : '';
    const seenRow = Number(deal.times_seen) > 0 ? `<dt>Times seen</dt><dd>${deal.times_seen}</dd>` : '';
    const hypeRow = (deal.market_cheaper && Number(deal.market_saving) < 0)
      ? `<dt>Market check</dt><dd>~${money(Math.abs(deal.market_saving))} cheaper elsewhere — verify</dd>`
      : '';
    return `<h2>${escapeHtml(deal.title)}</h2>
      <div class="drawer-save">${money(deal.savings)} ${escapeHtml(valueLine(deal))} · Agent Score ${qualityScore(deal)}/100</div>
      <div class="badges">${badges}</div>
      <dl>
        <dt>AI confidence</dt><dd>${aiConfidence(deal)}%</dd>
        <dt>Urgency</dt><dd>${urgencyScore(deal)}%</dd>
        <dt>Recommended action</dt><dd>${escapeHtml(agentAction(deal))}</dd>
        <dt>Agent read</dt><dd>${escapeHtml(agentInsight(deal))}</dd>
        ${hypeRow}
        <dt>Merchant</dt><dd>${escapeHtml(deal.merchant)}</dd>
        <dt>Category</dt><dd>${escapeHtml(deal.category)}</dd>
        <dt>Value benchmark</dt><dd>${money(deal.best_savings)} best detected saving</dd>
        ${lowestRow}
        ${seenRow}
        <dt>First detected</dt><dd>${new Date(deal.first_seen_at).toLocaleString()}</dd>
        <dt>Last checked</dt><dd>${new Date(deal.last_seen_at).toLocaleString()}</dd>
      </dl>
      <a class="drawer-link" href="${escapeHtml(deal.link)}" target="_blank" rel="noopener">Open OzBargain deal</a>`;
  }

  function openDetails(deal) {
    els.drawerContent.innerHTML = detailHtml(deal);
    els.drawer.hidden = false;
  }

  // ════════════════════════════════════════════════════════════════
  //  DEAL ASSISTANT — agentic engine
  //  Intent + slot extraction → tool registry → planner → rich answer.
  //  Optional generative brain via a serverless proxy (agent-config).
  // ════════════════════════════════════════════════════════════════
  const AGENT_CFG = (() => {
    try { return JSON.parse(document.querySelector('#agent-config').textContent); }
    catch (e) { return {}; }
  })();
  const POINTS = AGENT_CFG.points || { default: 0.01 };
  const POINT_ALIASES = AGENT_CFG.point_aliases || {};
  const GOALS = AGENT_CFG.goals || {};
  const LLM_ENDPOINT = AGENT_CFG.llm_endpoint || '';

  const convo = { lastRows: [], lastDeal: null, turns: [] };

  function num(s) { return Number(String(s == null ? '' : s).replace(/[^0-9.]/g, '')) || 0; }
  function fmtMoney(v) { return '$' + Math.round(v || 0).toLocaleString(); }
  function activePool() { return deals.filter(d => !isExpired(d)); }
  function uniqueMerchants() { return [...new Set(deals.map(d => String(d.merchant || '').toLowerCase()).filter(Boolean))]; }

  const CATEGORY_ALIASES = [
    ['Travel', /\b(travel|flight|airfare|hotel|airline|luggage|cruise|lounge|qantas|velocity|lifemiles|krisflyer|asia miles)\b/],
    ['Finance', /\b(finance|credit card|debit card|home loan|mortgage|insurance|hospital cover|extras cover|health cover|smsf|super|refinance|bank|offset|savings account|amex|american express)\b/],
    ['Business', /\b(pty ltd|ptd\. ltd|limited company|virtual office|company setup|establishment setup|amazon business|zeller|payment terminal|terminals|abn required)\b/],
    ['Gift Cards', /\b(gift card|gift cards|egift card|egift cards|edr dollars|store credit|voucher|coupon)\b/],
    ['Utilities', /\b(agl|energy locals|electricity|gas bill|fuel card|fuel cards|home select plan)\b/],
    ['Mobile', /\b(iphone|galaxy|pixel|motorola|moto|oppo|xiaomi|phone|smartphone|mobile|sim|esim|prepaid|optus|telstra|5g)\b/],
    ['Computing', /\b(laptop|macbook|computer|computing|pc|gaming pc|ssd|monitor|keyboard|mouse|nas|router|ubiquiti|printer)\b/],
    ['Electronics', /\b(tv|television|oled|qled|mini led|ipad|tablet|airpods|headphones|earbuds|camera|soundbar|subwoofer|speaker|hifi|sennheiser|projector|telescope|v mount battery|power station|anker|uhf radio|uniden)\b/],
    ['Gaming', /\b(gaming|xbox|playstation|ps5|nintendo|switch|steam|console|racing wheel|logitech g|lego)\b/],
    ['Tools', /\b(mitre saw|mechanic|mechanics tool|tool set|spanner|gearwrench|makita|battery charger|power tools|bunnings|sydney tools|stepladder|ladder)\b/],
    ['Smart Home', /\b(smart lock|aqara|ring spotlight|spotlight cam|security camera|doorbell)\b/],
    ['Home Appliances', /\b(vacuum|dyson|robot vacuum|dehumidifier|dehumidifiers|air purifier|fridge|washing machine|washer|dryer|dishwasher|karcher|spot cleaner|coffee machine|coffee grinder|nespresso|espresso|air fryer|cooktop|cooktops|multi cooker|instant pot|casserole pot|stock pot|fry pan|steel pan)\b/],
    ['Home', /\b(home|furniture|coffee table|mattress|sofa|standing desk|solar|garden|lawn mower|mower|automower|pressure washer)\b/],
    ['Outdoor', /\b(outdoor|hiking|camping|tent|cabana|beach cabana|sleeping bag|backpack|puffer|insulated jacket|rain jacket|columbia|north face|patagonia|macpac|bike|cycling|fitness)\b/],
    ['Automotive', /\b(automotive|driveaway|suv|ute|vehicle|ev charger|dash cam|tyres|car battery|byd|tesla|volkswagen|skoda|chery|sealion|tayron)\b/],
    ['Health', /\b(health|toothbrush|sonicare|oral-b|shaver|chemist|pharmacy|vitamin|supplement|skincare|sunscreen|cpap|hospital|oura ring)\b/],
    ['Baby & Kids', /\b(baby|kids|toy|toys|uppababy|pram|stroller|car seat|toddler)\b/],
    ['Fashion', /\b(fashion|watch|watches|footwear|shoe|shoes|sneaker|sneakers|adidas|allbirds|saucony|the iconic|athlete's foot|jacket|jackets|menswear|shirts|boots|clothing|apparel|sunglasses)\b/],
    ['Groceries', /\b(grocery|groceries|woolworths|coles|aldi|costco|wine|wines|cabernet|sauvignon|shiraz|beer|coffee beans|chocolate|nappies)\b/],
    ['Entertainment', /\b(movie|cinema|streaming|subscription|audible|spotify|netflix|disney|book|star wars|electronic helmet)\b/],
    ['Pets', /\b(pet|dog|cat|kibble|petstock|petbarn)\b/],
    ['Internet', /\b(nbn|broadband|internet plan|mobile broadband)\b/],
    ['Shopping', /\b(referee|referrer|first purchase|next purchase)\b/],
  ];

  const STOP = new Set(['a','an','and','any','are','around','ask','best','better','can','current','deal','deals','find','for','from','give','good','have','help','i','in','is','latest','list','me','now','of','offer','offers','on','or','please','present','relevant','result','results','right','search','show','some','the','these','this','to','top','what','which','with','about','me','my','you','your']);

  function tokenize(text) {
    const tokens = String(text || '').toLowerCase().match(/[a-z0-9]+(?:\.[a-z0-9]+)?/g) || [];
    return [...new Set(tokens.filter(t => t.length >= 2 && !STOP.has(t)))];
  }

  // ── Slot / entity extraction ───────────────────────────────────
  function extractSlots(text) {
    const s = {};
    let m;
    if ((m = text.match(/between\s*\$?\s*([\d,]+)\s*(?:and|-|to)\s*\$?\s*([\d,]+)/))) { s.priceMin = num(m[1]); s.priceMax = num(m[2]); }
    if ((m = text.match(/(?:under|below|less than|cheaper than|max|up to)\s*\$?\s*([\d,]+)/))) s.priceMax = num(m[1]);
    if ((m = text.match(/(?:over|above|more than|min|at least)\s*\$?\s*([\d,]+)/))) s.priceMin = num(m[1]);
    if ((m = text.match(/sav(?:e|ing|ings)\s*(?:of|over|above|at least|more than)?\s*\$?\s*([\d,]+)/))) s.savingsMin = num(m[1]);
    if ((m = text.match(/\btop\s*(\d{1,2})\b/)) || (m = text.match(/\b(\d{1,2})\s*(?:deals|results|options)\b/))) s.limit = Math.min(20, num(m[1]));

    // categories
    s.categories = CATEGORY_ALIASES.filter(([, re]) => re.test(text)).map(([c]) => c);
    // merchants present in data
    s.merchants = uniqueMerchants().filter(mn => mn && text.includes(mn));
    // metric
    if (/\burgenc|urgent|flash|ending|expir/.test(text)) s.metric = 'urgency';
    else if (/\bconfidence|reliab|trust/.test(text)) s.metric = 'confidence';
    else if (/\bscore|overall|best value\b/.test(text)) s.metric = 'score';
    else if (/\bsaving|discount|save\b/.test(text)) s.metric = 'savings';
    // points
    s.points = extractPoints(text);
    return s;
  }

  function extractPoints(text) {
    // e.g. "250k amex points", "250,000 MR", "100k velocity", "value of 80000 qantas points"
    const progKeys = Object.keys(POINT_ALIASES).sort((a, b) => b.length - a.length);
    let program = null;
    for (const key of progKeys) { if (text.includes(key)) { program = POINT_ALIASES[key]; break; } }
    const m = text.match(/([\d][\d,]*\.?\d*)\s*(k|thousand|m|million)?\s*(?:×|x)?\s*(?:point|pt|mr|mile|miles)?/);
    let amount = 0;
    if (m) {
      amount = num(m[1]);
      const unit = (m[2] || '').toLowerCase();
      if (unit === 'k' || unit === 'thousand') amount *= 1000;
      if (unit === 'm' || unit === 'million') amount *= 1000000;
    }
    if (!program && !/\b(point|pts|miles|mr|reward)\b/.test(text)) return null;
    return { program: program || 'default', amount };
  }

  // ── Intent classification ──────────────────────────────────────
  function classify(text, slots) {
    if (/\b(hi|hello|hey|yo|sup)\b/.test(text) && text.length < 12) return 'greeting';
    if (/\b(help|what can you do|capabilities|commands)\b/.test(text)) return 'help';
    if (slots.points && (/\b(worth|value|how much|valuation|convert)\b/.test(text) || /\bpoints?\b/.test(text))) return 'points_value';
    if (/\b(compare|versus|vs\.?|difference between|which is better)\b/.test(text)) return 'compare';
    if (/\b(how many|count|total|sum|average|avg|most|biggest|largest|highest|breakdown by)\b/.test(text)) return 'aggregate';
    if (/\bis\b.*\blowest\b|lowest (?:price )?(?:seen|tracked|ever|right now|now)|all-?time low|price history|good time to buy/.test(text)) return 'history';
    if (/\b(cheapest|least expensive|smallest price)\b/.test(text) || (/\blowest price\b/.test(text) && !/\bis\b/.test(text))) return 'cheapest';
    if (/\b(overpriced|hype|actually cheaper|worth it|real deal|trap|cheaper elsewhere)\b/.test(text)) return 'hype';
    if (/\b(cashback|stack|stacking|effective price|net price|true price|shopback|cashrewards)\b/.test(text)) return 'cashback';
    if (/\b(explain|why|tell me about|details on|break ?down|analyse|analyze)\b/.test(text)) return 'explain';
    if (/\b(goal|trip|holiday|setup|build|upgrade my|for my)\b/.test(text)) return 'goal';
    if (/\b(first|second|third|that one|those|them|it|the top|number \d)\b/.test(text) && convo.lastRows.length) return 'followup';
    return 'search';
  }

  // ── Reference resolution for follow-ups ────────────────────────
  function resolveReferences(text) {
    const rows = convo.lastRows;
    if (!rows.length) return [];
    const ord = { first: 0, '1st': 0, one: 0, second: 1, '2nd': 1, two: 1, third: 2, '3rd': 2, three: 2, fourth: 3, fifth: 4 };
    const picks = [];
    for (const [word, idx] of Object.entries(ord)) {
      if (new RegExp('\\b' + word + '\\b').test(text) && rows[idx]) picks.push(rows[idx]);
    }
    const numMatch = text.match(/\bnumber\s*(\d{1,2})\b/);
    if (numMatch && rows[num(numMatch[1]) - 1]) picks.push(rows[num(numMatch[1]) - 1]);
    if (/\b(those|them|these|all of them)\b/.test(text) && !picks.length) return rows.slice(0, 5);
    if (/\b(it|that one|that deal)\b/.test(text) && !picks.length && convo.lastDeal) return [convo.lastDeal];
    return picks;
  }

  // ── Tools over the deal data ───────────────────────────────────
  function toolFilter(rows, slots, text) {
    let out = rows.slice();
    if (slots.priceMax) out = out.filter(d => d.deal_price > 0 && d.deal_price <= slots.priceMax);
    if (slots.priceMin) out = out.filter(d => d.deal_price >= slots.priceMin);
    if (slots.savingsMin) out = out.filter(d => d.savings >= slots.savingsMin);
    if (slots.categories && slots.categories.length) {
      const set = new Set(slots.categories);
      out = out.filter(d => set.has(d.category) || slots.categories.some(c => dealText(d).includes(c.toLowerCase())));
    }
    if (slots.merchants && slots.merchants.length) out = out.filter(d => slots.merchants.some(mn => String(d.merchant || '').toLowerCase().includes(mn)));
    const kw = tokenize(text).filter(t => !['deal', 'deals', 'cheap', 'cheapest', 'best', 'find', 'show', 'good', 'under', 'over', 'between', 'top', 'price', 'prices'].includes(t));
    if (kw.length) {
      const scored = out.map(d => {
        const textBlob = dealText(d);
        const tokens = dealTokens(d);
        const score = kw.reduce((sc, t) => {
          if (tokens.has(t)) return sc + 4;
          if (textBlob.includes(t)) return sc + 1;
          return sc;
        }, 0);
        return [d, score];
      }).filter(([, sc]) => sc > 0);
      if (!scored.length) return [];
      scored.sort((a, b) => b[1] - a[1] || b[0].savings - a[0].savings);
      out = scored.map(([d]) => d);
    }
    return out;
  }

  function toolRank(rows, metric) {
    const r = rows.slice();
    if (metric === 'urgency') r.sort((a, b) => urgencyScore(b) - urgencyScore(a) || b.savings - a.savings);
    else if (metric === 'confidence') r.sort((a, b) => aiConfidence(b) - aiConfidence(a) || b.savings - a.savings);
    else if (metric === 'score') r.sort((a, b) => qualityScore(b) - qualityScore(a) || b.savings - a.savings);
    else r.sort((a, b) => b.savings - a.savings || qualityScore(b) - qualityScore(a));
    return r;
  }

  function pointsValue(program, amount) {
    const cpp = POINTS[program] != null ? POINTS[program] : POINTS.default;
    return { cpp, value: Math.round(amount * cpp) };
  }

  function effectivePrice(deal) {
    const layers = [];
    layers.push({ label: 'Deal price', value: deal.deal_price > 0 ? fmtMoney(deal.deal_price) : '—' });
    layers.push({ label: 'Potential saving', value: fmtMoney(deal.savings), good: true });
    if (deal.cashback_platform) layers.push({ label: 'Cashback', value: deal.cashback_platform + ' (check live rate)', note: true });
    if (deal.price_beat_count > 0) layers.push({ label: 'Price-beat', value: deal.price_beat_count + ' store' + (deal.price_beat_count > 1 ? 's' : '') });
    if (deal.lowest_price > 0) layers.push({ label: 'Lowest tracked', value: fmtMoney(deal.lowest_price) + (deal.is_lowest_price ? ' (now lowest)' : ''), good: deal.is_lowest_price });
    if (deal.market_cheaper && Number(deal.market_saving) < 0) layers.push({ label: 'Market check', value: '~' + fmtMoney(Math.abs(deal.market_saving)) + ' cheaper elsewhere', warn: true });
    return layers;
  }

  // ── Rich rendering ─────────────────────────────────────────────
  function chipHtml(deal) {
    const tags = [];
    if (deal.cashback_platform) tags.push('Cashback');
    if (deal.is_lowest_price) tags.push('Lowest price');
    if (isTimeSensitive(deal)) tags.push('Time-sensitive');
    if (deal.market_cheaper && Number(deal.market_saving) < 0) tags.push('⚠ Verify price');
    const tagHtml = tags.map(t => `<span class="ac-tag">${escapeHtml(t)}</span>`).join('');
    return `<a class="ac-deal" href="${escapeHtml(deal.link)}" target="_blank" rel="noopener">
      <div class="ac-deal-main">
        <div class="ac-deal-title">${escapeHtml(deal.title)}</div>
        <div class="ac-deal-meta">${escapeHtml(deal.merchant)} · ${escapeHtml(deal.category)} · AI ${aiConfidence(deal)}% · Urgency ${urgencyScore(deal)}%</div>
        ${tagHtml ? `<div class="ac-tags">${tagHtml}</div>` : ''}
      </div>
      <div class="ac-deal-save">${fmtMoney(deal.savings)}</div>
    </a>`;
  }

  function dealListHtml(rows, limit) {
    return `<div class="ac-deals">${rows.slice(0, limit || 5).map(chipHtml).join('')}</div>`;
  }

  function breakdownHtml(deal) {
    const rows = effectivePrice(deal).map(l =>
      `<div class="ac-brk-row${l.warn ? ' warn' : ''}${l.good ? ' good' : ''}"><span>${escapeHtml(l.label)}</span><span>${escapeHtml(l.value)}</span></div>`
    ).join('');
    return `<div class="ac-breakdown">${rows}</div>`;
  }

  function comparisonHtml(a, b) {
    const row = (label, va, vb, betterA, betterB) =>
      `<tr><th>${escapeHtml(label)}</th><td class="${betterA ? 'win' : ''}">${escapeHtml(va)}</td><td class="${betterB ? 'win' : ''}">${escapeHtml(vb)}</td></tr>`;
    return `<table class="ac-compare">
      <thead><tr><th></th><th>${escapeHtml(a.title.slice(0, 40))}</th><th>${escapeHtml(b.title.slice(0, 40))}</th></tr></thead>
      <tbody>
        ${row('Saving', fmtMoney(a.savings), fmtMoney(b.savings), a.savings >= b.savings, b.savings > a.savings)}
        ${row('Price', a.deal_price ? fmtMoney(a.deal_price) : '—', b.deal_price ? fmtMoney(b.deal_price) : '—', a.deal_price && a.deal_price <= (b.deal_price || 1e9), b.deal_price && b.deal_price < (a.deal_price || 1e9))}
        ${row('AI confidence', aiConfidence(a) + '%', aiConfidence(b) + '%', aiConfidence(a) >= aiConfidence(b), aiConfidence(b) > aiConfidence(a))}
        ${row('Urgency', urgencyScore(a) + '%', urgencyScore(b) + '%', urgencyScore(a) >= urgencyScore(b), urgencyScore(b) > urgencyScore(a))}
        ${row('Agent score', qualityScore(a) + '/100', qualityScore(b) + '/100', qualityScore(a) >= qualityScore(b), qualityScore(b) > qualityScore(a))}
        ${row('Cashback', a.cashback_platform ? 'Yes' : 'No', b.cashback_platform ? 'Yes' : 'No', !!a.cashback_platform, !!b.cashback_platform)}
      </tbody>
    </table>`;
  }

  // ── Intent handlers → { text, html, rows } ─────────────────────
  function handleGreeting() {
    return { text: "Hi Eswar — I'm your deal analyst. Ask me things like “best tech deals under $1000”, “compare the top two”, “how much is 250k Amex points worth”, “what's the effective price of the Dyson”, or “how many finance deals are there”." };
  }

  function handleHelp() {
    return { text: "I can: rank and filter deals (price, saving, category, merchant, urgency, confidence); compute points valuations using your redemption rates; show effective price with cashback and price-beat stacking; flag deals where the market is actually cheaper; check lowest-tracked price; compare two deals side by side; aggregate (counts, totals, averages, biggest); and handle follow-ups like “compare those” or “the cheapest of them”." };
  }

  function handlePoints(text, slots) {
    const p = slots.points;
    if (!p || !p.amount) return { text: "Tell me the amount and program — e.g. “how much is 250k Velocity worth” or “value of 100,000 Amex MR points”." };
    const { cpp, value } = pointsValue(p.program, p.amount);
    const label = p.program === 'default' ? 'points' : p.program.replace('_', ' ');
    const related = activePool().filter(d => /\b(point|qantas|velocity|amex|mr|miles|frequent flyer|transfer bonus)\b/i.test(d.title)).slice(0, 3);
    convo.lastRows = related;
    return {
      text: `${p.amount.toLocaleString()} ${label} ≈ ${fmtMoney(value)} at ${(cpp).toFixed(4)} $/pt (your redemption value).` + (related.length ? ' Related points deals live now:' : ''),
      html: related.length ? dealListHtml(related, 3) : '',
    };
  }

  function handleAggregate(text, slots) {
    const hasFilter = !!(slots.priceMax || slots.priceMin || slots.savingsMin || (slots.categories && slots.categories.length) || (slots.merchants && slots.merchants.length));
    let rows = toolFilter(activePool(), slots, text);
    if (!rows.length && !hasFilter) rows = activePool();
    const totalSav = rows.reduce((s, d) => s + d.savings, 0);
    const avg = rows.length ? Math.round(totalSav / rows.length) : 0;
    const biggest = rows.slice().sort((a, b) => b.savings - a.savings)[0];
    if (/\bhow many|count\b/.test(text)) {
      const byCat = {};
      for (const d of rows) byCat[d.category] = (byCat[d.category] || 0) + 1;
      const breakdown = Object.entries(byCat).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${c}: ${n}`).join(' · ');
      return { text: `${rows.length} matching active deals.` + (breakdown ? ` By category — ${breakdown}.` : '') };
    }
    if (/\baverage|avg\b/.test(text)) return { text: `Average saving across ${rows.length} matching deals is ${fmtMoney(avg)} (total ${fmtMoney(totalSav)}).` };
    if (/\b(biggest|largest|highest|most)\b/.test(text) && biggest) {
      convo.lastDeal = biggest; convo.lastRows = [biggest];
      return { text: `Biggest saving is ${fmtMoney(biggest.savings)}:`, html: chipHtml(biggest) };
    }
    return { text: `${rows.length} matching deals worth ${fmtMoney(totalSav)} in total savings (avg ${fmtMoney(avg)}).` };
  }

  function handleCheapest(text, slots) {
    let rows = toolFilter(activePool(), slots, text).filter(d => d.deal_price > 0);
    rows.sort((a, b) => a.deal_price - b.deal_price);
    if (!rows.length) return { text: "I couldn't find priced deals matching that. Try a category or product." };
    convo.lastRows = rows.slice(0, 5); convo.lastDeal = rows[0];
    return { text: `Cheapest matching ${rows.length > 1 ? 'options' : 'option'} by price:`, html: dealListHtml(rows, slots.limit || 5) };
  }

  function handleHistory(text, slots) {
    let rows = toolFilter(activePool(), slots, text);
    const named = rows.length === 1 || (rows.length && /\b(of the|for the|the|is the)\b/.test(text)) ? rows[0] : null;
    const target = resolveReferences(text)[0] || named || convo.lastDeal || rows[0];
    if (!target) return { text: "Point me at a deal first — e.g. search for it, then ask if it's the lowest." };
    convo.lastDeal = target;
    if (target.lowest_price > 0) {
      const verdict = target.is_lowest_price ? "this is the lowest price I've tracked — a genuinely good window." : `not the lowest — I've tracked it as low as ${fmtMoney(target.lowest_price)}.`;
      return { text: `${target.title}: ${verdict}`, html: breakdownHtml(target) };
    }
    return { text: `${target.title}: I don't have enough price history yet to call a low. Current saving ${fmtMoney(target.savings)}.`, html: breakdownHtml(target) };
  }

  function handleHype(text, slots) {
    const traps = activePool().filter(d => d.market_cheaper && Number(d.market_saving) < 0);
    if (traps.length) {
      traps.sort((a, b) => a.market_saving - b.market_saving);
      convo.lastRows = traps;
      return { text: `${traps.length} deal${traps.length > 1 ? 's' : ''} where the market is actually cheaper than the OzBargain price — verify before buying:`, html: dealListHtml(traps, 5) };
    }
    return { text: "No live hype traps right now — none of the priced deals are beaten by current market price in my data. (Enable market-price lookup in the monitor to strengthen this check.)" };
  }

  function handleCashback(text, slots) {
    let target = resolveReferences(text)[0] || convo.lastDeal;
    if (!target) {
      // try to locate a specifically-named product (e.g. "effective price of the dyson")
      const named = toolFilter(activePool(), slots, text);
      if (named.length === 1 || (named.length && /\b(of the|for the|the)\b/.test(text))) target = named[0];
    }
    if (target) { convo.lastDeal = target; return { text: `Effective-price breakdown for ${target.title}:`, html: breakdownHtml(target) }; }
    let rows = toolFilter(activePool(), slots, text).filter(d => d.cashback_platform);
    if (!rows.length) rows = activePool().filter(d => d.cashback_platform);
    rows.sort((a, b) => b.savings - a.savings);
    convo.lastRows = rows;
    if (!rows.length) return { text: "No deals currently flag a cashback platform. I can still show effective price for any specific deal — name one." };
    return { text: `Deals with a cashback layer available (stack on top of the listed saving — check the live rate):`, html: dealListHtml(rows, 5) };
  }

  function handleExplain(text, slots) {
    const target = resolveReferences(text)[0] || toolFilter(activePool(), slots, text)[0] || convo.lastDeal;
    if (!target) return { text: "Which deal? Search for it first, or name the product." };
    convo.lastDeal = target;
    return {
      text: `${target.title} — ${valueSignal(target).toLowerCase()}: ${agentAction(target).toLowerCase()}. ${aiConfidence(target)}% confidence, ${urgencyScore(target)}% urgency. ${agentInsight(target)}.`,
      html: breakdownHtml(target),
    };
  }

  function handleCompare(text, slots) {
    let picks = resolveReferences(text);
    if (picks.length < 2) {
      const pool = toolFilter(activePool(), slots, text);
      picks = (convo.lastRows.length >= 2 ? convo.lastRows : pool).slice(0, 2);
    }
    if (picks.length < 2) return { text: "Give me two things to compare — e.g. “compare the top two” after a search, or name two products." };
    convo.lastRows = picks;
    const [a, b] = picks;
    const winner = qualityScore(a) >= qualityScore(b) ? a : b;
    return { text: `Comparing the two — on balance ${winner === a ? 'the first' : 'the second'} looks stronger:`, html: comparisonHtml(a, b) };
  }

  function handleGoal(text, slots) {
    let goalKey = null;
    for (const [g, kws] of Object.entries(GOALS)) { if (text.includes(g) || kws.some(k => text.includes(k))) { goalKey = g; break; } }
    const kws = goalKey ? GOALS[goalKey] : tokenize(text);
    let rows = activePool().filter(d => kws.some(k => dealText(d).includes(k)));
    rows = toolRank(rows, slots.metric || 'score');
    convo.lastRows = rows;
    if (!rows.length) return { text: `No live deals match that goal right now. I'll keep watching — try a broader term or a category.` };
    return { text: `Deals that fit${goalKey ? ' your ' + goalKey + ' goal' : ''}, best first:`, html: dealListHtml(rows, slots.limit || 5) };
  }

  function handleSearch(text, slots) {
    let rows = toolFilter(activePool(), slots, text);
    rows = toolRank(rows, slots.metric);
    convo.lastRows = rows;
    if (!rows.length) return { text: "No active deals match that. Try a category, merchant, product, a price like “under $500”, or ask for urgent/high-confidence deals." };
    const lead = slots.metric === 'urgency' ? 'Most time-sensitive matches:'
      : slots.metric === 'confidence' ? 'Highest-confidence matches:'
      : slots.priceMax || slots.priceMin ? 'Matches in that price range:'
      : 'Strongest matches:';
    return { text: lead, html: dealListHtml(rows, slots.limit || 5) };
  }

  // ── Local planner ──────────────────────────────────────────────
  function localRespond(prompt) {
    const text = prompt.toLowerCase().trim();
    const slots = extractSlots(text);
    let intent = classify(text, slots);
    if (intent === 'followup') {
      if (/\bcompare\b/.test(text)) intent = 'compare';
      else if (/\bcheapest\b/.test(text)) intent = 'cheapest';
      else if (/\bcashback|effective|net price\b/.test(text)) intent = 'cashback';
      else intent = 'explain';
    }
    const H = {
      greeting: handleGreeting, help: handleHelp, points_value: handlePoints,
      aggregate: handleAggregate, cheapest: handleCheapest, history: handleHistory,
      hype: handleHype, cashback: handleCashback, explain: handleExplain,
      compare: handleCompare, goal: handleGoal, search: handleSearch,
    };
    const fn = H[intent] || handleSearch;
    const res = fn(text, slots) || { text: "I'm not sure how to help with that yet — try rephrasing." };
    convo.turns.push({ q: prompt, intent });
    return res;
  }

  // ── Optional generative brain (serverless proxy) ───────────────
  async function llmRespond(prompt) {
    const compact = activePool().slice(0, 60).map(d => ({
      title: d.title, merchant: d.merchant, category: d.category, savings: d.savings,
      deal_price: d.deal_price, market_price: d.market_price, link: d.link,
      cashback: !!d.cashback_platform, lowest_price: d.lowest_price, is_lowest: d.is_lowest_price,
      urgency: urgencyScore(d), confidence: aiConfidence(d),
    }));
    const resp = await fetch(LLM_ENDPOINT, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: prompt, deals: compact, points: POINTS, history: convo.turns.slice(-6) }),
    });
    if (!resp.ok) throw new Error('proxy ' + resp.status);
    const data = await resp.json();
    return { text: data.reply || data.text || '(no reply)', html: data.html || '' };
  }

  // ── Rendering ──────────────────────────────────────────────────
  function addChatMessage(role, payload) {
    const message = document.createElement('div');
    message.className = `chat-message ${role}`;
    if (typeof payload === 'string') payload = { text: payload };
    if (payload.text) {
      const p = document.createElement('div');
      p.className = 'ac-text';
      p.textContent = payload.text;
      message.append(p);
    }
    if (payload.html) {
      const wrap = document.createElement('div');
      wrap.className = 'ac-rich';
      wrap.innerHTML = payload.html;
      message.append(wrap);
    }
    els.chatLog.append(message);
    els.chatLog.scrollTop = els.chatLog.scrollHeight;
  }

  function setThinking(on) {
    let t = els.chatLog.querySelector('.chat-thinking');
    if (on && !t) {
      t = document.createElement('div');
      t.className = 'chat-message assistant chat-thinking';
      t.innerHTML = '<span class="ac-dot"></span><span class="ac-dot"></span><span class="ac-dot"></span>';
      els.chatLog.append(t);
      els.chatLog.scrollTop = els.chatLog.scrollHeight;
    } else if (!on && t) { t.remove(); }
  }

  async function askAssistant(prompt) {
    const question = String(prompt || '').trim();
    if (!question) return;
    addChatMessage('user', question);
    els.chatInput.value = '';
    if (LLM_ENDPOINT) {
      setThinking(true);
      try {
        const res = await llmRespond(question);
        setThinking(false);
        addChatMessage('assistant', res);
        return;
      } catch (e) {
        setThinking(false);
        // graceful fallback to the local agent
      }
    }
    addChatMessage('assistant', localRespond(question));
  }

  els.toggle.addEventListener('click', () => {
    const hidden = els.panel.toggleAttribute('hidden');
    els.toggle.setAttribute('aria-expanded', String(!hidden));
  });
  els.resetButtons.forEach(button => button.addEventListener('click', resetFilters));
  els.drawerClose.addEventListener('click', () => els.drawer.hidden = true);
  document.querySelectorAll('.preset').forEach(button => {
    button.addEventListener('click', () => applyPreset(button.dataset.preset));
  });
  els.categorySummary.addEventListener('click', event => {
    const button = event.target.closest('.cat-chip');
    if (!button) return;
    els.category.value = button.dataset.category || 'All';
    applyFilters();
  });
  els.topStrip.addEventListener('click', event => {
    const presetButton = event.target.closest('.link-button');
    if (!presetButton) return;
    applyPreset(presetButton.dataset.preset);
  });
  els.urgentStrip.addEventListener('click', event => {
    const button = event.target.closest('.mini-deal');
    if (!button) return;
    const urgent = [...currentFocusRows].filter(isTimeSensitive).sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a)));
    openDetails(urgent[Number(button.dataset.urgentIndex)]);
  });
  els.grid.addEventListener('click', event => {
    const button = event.target.closest('.details');
    if (!button) return;
    openDetails(currentRows[Number(button.dataset.index)]);
  });
  els.todayGrid.addEventListener('click', event => {
    const button = event.target.closest('.details');
    if (!button) return;
    openDetails(currentTodayRows[Number(button.dataset.index)]);
  });
  els.topStrip.addEventListener('click', event => {
    const button = event.target.closest('.mini-deal');
    if (!button) return;
    const top = [...currentFocusRows].sort((a, b) => (b.savings - a.savings) || (qualityScore(b) - qualityScore(a)));
    openDetails(top[Number(button.dataset.topIndex)]);
  });
  els.chatForm.addEventListener('submit', event => {
    event.preventDefault();
    askAssistant(els.chatInput.value);
  });
  els.chatClear.addEventListener('click', () => {
    els.chatLog.innerHTML = '';
    addChatMessage('assistant', 'Ask me for best deals, urgent offers, cashback risk, or a product/category you care about.');
  });
  document.querySelectorAll('[data-chat-prompt]').forEach(button => {
    button.addEventListener('click', () => askAssistant(button.dataset.chatPrompt || ''));
  });
  for (const el of [els.search, els.category, els.merchant, els.minSaving, els.sort, els.watchlist, els.agentPicksOnly, els.urgentOnly, els.hideExpired]) {
    el.addEventListener('input', applyFilters);
    el.addEventListener('change', applyFilters);
  }

  // Floating Deal Assistant launcher
  (function () {
    const fab = document.getElementById('chat-fab');
    const dock = document.getElementById('chat-dock');
    const closeBtn = document.getElementById('chat-dock-close');
    if (fab && dock) {
      const openDock = () => {
        dock.hidden = false;
        fab.setAttribute('aria-expanded', 'true');
        fab.classList.add('is-open');
        requestAnimationFrame(() => dock.classList.add('is-visible'));
        setTimeout(() => { if (els.chatInput) els.chatInput.focus(); }, 140);
      };
      const closeDock = () => {
        dock.classList.remove('is-visible');
        fab.setAttribute('aria-expanded', 'false');
        fab.classList.remove('is-open');
        setTimeout(() => { dock.hidden = true; }, 200);
      };
      fab.addEventListener('click', () => { dock.hidden ? openDock() : closeDock(); });
      if (closeBtn) closeBtn.addEventListener('click', closeDock);
      document.addEventListener('keydown', e => { if (e.key === 'Escape' && !dock.hidden) closeDock(); });
    }
  })();

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
