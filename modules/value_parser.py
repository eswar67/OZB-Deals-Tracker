"""
modules/value_parser.py

Fast regex-based savings extractor from OZB deal titles.
No API calls — parses price patterns directly from the title string.

Returns: {"savings": int, "explanation": str, "deal_price": int}

Patterns handled (in priority order):
  0. Combined cart/trade-in discounts e.g. "$550 off in cart + $450 trade-in bonus"
  1. "Save $X"  /  "$X off"  /  "$X saving"
  2. "Was $Y, Now $X"  /  "$X (Was $Y)"  /  "RRP $Y ... $X"
  3. "X% off $Y"  →  savings = Y × X%
  4. Bundled free item with stated value  e.g. "+ Free Buds ($Y)"
  5. Points bonuses  e.g. "50,000 Qantas Points"
  6. Gift card discount  e.g. "$100 gift card for $80"
"""

import re
import logging

log = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _price(s: str) -> int:
    """Extract integer dollar amount from a string like '$1,299.00' → 1299."""
    s = s.replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return int(float(m.group(1))) if m else 0


def _all_prices(title: str) -> list:
    """Return all dollar amounts found in title, in order."""
    return [int(float(x.replace(",", ""))) for x in re.findall(r"\$\s*([\d,]+(?:\.\d+)?)", title)]


# ── Pattern matchers (return (savings, explanation) or None) ──────────────────

def _match_combined_trade_in_discount(t: str):
    """Sum stacked cart/off discounts and trade-in bonuses in the same title."""
    if not re.search(r"\btrade[-\s]?in\b", t, re.IGNORECASE):
        return None

    components = []
    seen_spans = set()
    patterns = [
        ("cart discount", r"\$\s*([\d,]+)\s*(?:off\b(?:\s+in\s+cart)?|cart\s+discount)"),
        ("trade-in bonus", r"\$\s*([\d,]+)\s*(?:trade[-\s]?in\s+bonus|trade\s+bonus)"),
        ("trade-in bonus", r"(?:trade[-\s]?in\s+bonus|trade\s+bonus)\s*(?:of\s+)?\$\s*([\d,]+)"),
    ]
    for label, pat in patterns:
        for m in re.finditer(pat, t, re.IGNORECASE):
            if m.span() in seen_spans:
                continue
            value = _price(m.group(1))
            if value > 0:
                seen_spans.add(m.span())
                components.append((label, value))

    if len(components) < 2:
        return None

    total = sum(value for _, value in components)
    if total <= 0:
        return None
    detail = " + ".join(f"${value:,} {label}" for label, value in components)
    return total, f"Combined discount stack: {detail} = ${total:,} potential saving"


def _match_explicit_save(t: str):
    """'Save $200', '$200 off', '$200 saving'"""
    for pat in [
        r"save\s+\$\s*([\d,]+)",
        r"\$\s*([\d,]+)\s*off\b",
        r"\$\s*([\d,]+)\s*saving",
        r"saving\s+of\s+\$\s*([\d,]+)",
        r"discount\s+of\s+\$\s*([\d,]+)",
    ]:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            s = _price(m.group(1))
            if s > 0:
                return s, f"Explicit saving of ${s:,} stated in title"
    return None


def _match_was_now(t: str):
    """'Was $499, Now $279'  /  '$279 (Was $499)'  /  'Normally $499'"""
    patterns = [
        # Was $Y [,/] Now $X
        r"was\s+\$\s*([\d,]+)[^$]*?(?:now|for)\s+\$\s*([\d,]+)",
        # $X (Was $Y)
        r"\$\s*([\d,]+)[^$]*?\bwas\b[^$]*?\$\s*([\d,]+)",
        # Normally/Usually $Y, now $X
        r"(?:normally|usually|orig(?:inally)?)\s+\$\s*([\d,]+)[^$]*?(?:now|for)?\s+\$\s*([\d,]+)",
        # Down from $Y to $X
        r"down\s+from\s+\$\s*([\d,]+)[^$]*?to\s+\$\s*([\d,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            a, b = _price(m.group(1)), _price(m.group(2))
            was_price, deal_price = (a, b) if a > b else (b, a)
            savings = was_price - deal_price
            if savings > 0:
                return savings, f"Was ${was_price:,} → now ${deal_price:,} = ${savings:,} saving"
    return None


def _match_rrp(t: str):
    """'RRP $499' combined with a deal price elsewhere in title."""
    rrp_m = re.search(r"\brrp\b[:\s]*\$\s*([\d,]+)", t, re.IGNORECASE)
    if not rrp_m:
        return None
    rrp = _price(rrp_m.group(1))
    if rrp == 0:
        return None

    deal_price = _extract_deal_price(t)
    if not (0 < deal_price < rrp):
        return None
    savings = rrp - deal_price
    if savings > 0:
        return savings, f"RRP ${rrp:,} − deal ${deal_price:,} = ${savings:,} saving"
    return None


def _match_percent_off(t: str):
    """'50% off' with a deal price — derive saving from deal price."""
    m = re.search(r"([\d.]+)\s*%\s*off", t, re.IGNORECASE)
    if not m:
        return None
    pct = float(m.group(1))
    if pct <= 0 or pct >= 100:
        return None

    # The deal price is the headline price, not a per-unit price in parentheses.
    deal_price = _extract_deal_price(t)
    if deal_price == 0:
        return None
    original = deal_price / (1 - pct / 100)
    savings = int(original - deal_price)
    if savings > 0:
        return savings, f"{pct:.0f}% off ${deal_price:,} = ~${savings:,} saving"
    return None


def _match_gift_card(t: str):
    """'$100 gift card for $80'  /  '10% off gift cards'."""
    # Explicit: $face for $price
    m = re.search(
        r"\$\s*([\d,]+)\s*(?:gift\s*card|voucher|store\s*credit)[^$]*?for\s+\$\s*([\d,]+)",
        t, re.IGNORECASE
    )
    if m:
        face, price = _price(m.group(1)), _price(m.group(2))
        if face > price > 0:
            return face - price, f"${face:,} gift card for ${price:,} = ${face-price:,} saving"
    return None


def _match_spend_get_value(t: str):
    """'Spend $1000 and get a $250 voucher' → saving is the reward value, not spend minus reward."""
    patterns = [
        r"spend\s+\$\s*[\d,]+[^$]{0,80}?\bget\s+(?:a\s+)?\$\s*([\d,]+)\s*(?:voucher|gift\s*card|credit|cashback|cash\s*back|bonus)",
        r"\bget\s+(?:a\s+)?\$\s*([\d,]+)\s*(?:voucher|gift\s*card|credit|cashback|cash\s*back|bonus)[^$]{0,80}?spend\s+\$\s*[\d,]+",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            value = _price(m.group(1))
            if value > 0:
                return value, f"${value:,} reward value stated in title"
    return None


def _match_reward_value(t: str):
    """'Get $300/$600 EDR Dollars' → count the stated reward value."""
    m = re.search(
        r"\b(?:get|receive|bonus|reward)\b.{0,100}?\b(?:voucher|gift\s*card|credit|cashback|cash\s*back|edr\s*dollars?|dollars?)\b",
        t,
        re.IGNORECASE,
    )
    if not m:
        return None
    values = _all_prices(m.group(0))
    if not values:
        return None
    value = max(values)
    if value > 0:
        return value, f"${value:,} reward value stated in title"
    return None


def _extract_gift_product_name(text: str) -> str:
    """
    Extract the product name from a free/bonus gift mention in deal title/description.
    Returns the best product name string to search for, or "" if nothing found.

    Examples:
      "Bonus S24+ 256GB"           → "Samsung Galaxy S24+"
      "Free Galaxy Buds2 Pro"      → "Samsung Galaxy Buds2 Pro"
      "Includes AirPods Pro 2nd"   → "Apple AirPods Pro"
      "+ Free Dyson V12"           → "Dyson V12"
    """
    # Normalise
    t = re.sub(r"<[^>]+>", " ", text)  # strip HTML
    t = re.sub(r"\s+", " ", t).strip()

    # Patterns: look for "free/bonus/includes/bundled [product name]"
    patterns = [
        r"(?:free|bonus|bundled?|includes?|plus|\+)\s+([A-Z][A-Za-z0-9 \+\-]{3,50}?)(?:\s+\d+GB|\s+\d+TB|\s+\(|\s+@|\s+Shipped|$|,)",
        r"([A-Z][A-Za-z0-9 \+\-]{3,50}?)\s+(?:for free|included free|as a bonus)",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            name = m.group(1).strip()
            # Filter out generic words that aren't product names
            skip = {"deal","item","product","gift","voucher","card","shipping","delivery","month"}
            if name.lower() not in skip and len(name) > 4:
                return name
    return ""


def _match_free_bundle(t: str, use_live_lookup: bool = False):
    """
    Detect free bundled items:
      1. Explicitly stated value: 'Free X (worth $Y)' / 'Free X valued at $Y'
      2. Live StaticICE price lookup for the detected product name
         (only when use_live_lookup=True — skipped in fast regex-only path)
    """
    # 1. Explicitly stated value — always fast, no API needed
    for pat in [
        r"free[^$]*?\((?:worth|valued?(?:\s+at)?)\s+\$\s*([\d,]+)\)",
        r"free[^$]*?worth\s+\$\s*([\d,]+)",
        r"free[^$]*?valued?\s+at\s+\$\s*([\d,]+)",
        r"bonus[^$]*?worth\s+\$\s*([\d,]+)",
    ]:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            v = _price(m.group(1))
            if v > 0:
                return v, f"Free item(s) worth ${v:,} bundled (stated)"

    # Only proceed if "free" / "bonus" keyword present
    if not re.search(r"\bfree\b|\bbonus\b|\bbundled?\b|\bincluded?\b", t, re.IGNORECASE):
        return None

    # 2. Live lookup — extract product name then query Claude for current AU price
    if use_live_lookup:
        product_name = _extract_gift_product_name(t)
        if product_name:
            try:
                from modules.price_intel import lookup_gift_price_claude
                import os, anthropic as _anthropic
                _client = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                price = lookup_gift_price_claude(product_name, _client)
                if price > 0:
                    return price, f"Free gift(s): {product_name} (~${price:,} AU market price)"
            except Exception as e:
                log.debug(f"Live gift lookup failed: {e}")

    return None


# Point valuations loaded from user-prefs.json (no hardcoded constants).
def _load_point_values() -> dict:
    """Load AUD-per-point values from user-prefs.json points_value_per_point_aud."""
    import json
    from pathlib import Path
    prefs_file = Path(__file__).parent.parent / "user-prefs.json"
    try:
        cfg = json.loads(prefs_file.read_text()).get("points_value_per_point_aud", {})
        return {k: v for k, v in cfg.items() if not k.startswith("_")}
    except Exception as e:
        log.warning(f"Could not load point values from user-prefs.json: {e}")
        return {}

_POINT_VALUES = _load_point_values()
QANTAS_CPP   = _POINT_VALUES.get("qantas",   _POINT_VALUES.get("default", 0.0135))
VELOCITY_CPP = _POINT_VALUES.get("velocity", _POINT_VALUES.get("default", 0.0135))


def _match_points(t: str):
    """
    Match loyalty points bonuses in CC/travel deal titles.

    Handles patterns like:
      - "130,000 Bonus Qantas Points"        (words between number and brand)
      - "90,000 QFF/VFF"                     (abbreviations)
      - "110,000 Bonus Qantas Points"
      - "80,000 Velocity Frequent Flyer Points"
      - "50,000 Qantas Points"               (classic form)

    Excluded: "discount when purchasing X points" — that's a points-buying deal,
    not a points-earning deal. Return None so Claude handles it properly.
    """
    # Guard: "purchasing/buying/transferring points" = discount on buying, not a bonus
    # Use a broad match: "purchasing" (anywhere) + "points" within 80 chars
    if re.search(r"\b(?:purchas|buying|transfer|redeem)\w*\b.{0,80}\bpoints?\b", t, re.IGNORECASE):
        return None
    # ── Qantas: number … [words] … qantas/qff … [words] … points ─────────────
    # Covers: "130,000 Bonus Qantas Points", "50,000 Qantas Frequent Flyer Points"
    m = re.search(
        r"([\d,]+)[^$\n]{0,25}?(?:qantas|qff)(?:[^$\n]{0,30}?(?:frequent\s+flyer\s+)?points?)?",
        t, re.IGNORECASE
    )
    if m:
        pts = _price(m.group(1))
        val = int(pts * QANTAS_CPP)
        if val > 0:
            return val, f"{pts:,} Qantas pts × ${QANTAS_CPP} = ${val:,}"

    # ── Velocity / VFF ────────────────────────────────────────────────────────
    m = re.search(
        r"([\d,]+)[^$\n]{0,25}?(?:velocity|vff)(?:[^$\n]{0,30}?points?)?",
        t, re.IGNORECASE
    )
    if m:
        pts = _price(m.group(1))
        val = int(pts * VELOCITY_CPP)
        if val > 0:
            return val, f"{pts:,} Velocity pts × ${VELOCITY_CPP} = ${val:,}"

    # ── QFF/VFF combo abbreviation (e.g. "90,000 QFF/VFF") ───────────────────
    # Already covered above (qff matched first), but keep as fallback
    m = re.search(r"([\d,]+)\s*qff\s*/\s*vff", t, re.IGNORECASE)
    if m:
        pts = _price(m.group(1))
        val = int(pts * QANTAS_CPP)   # treat as Qantas value (conservative)
        if val > 0:
            return val, f"{pts:,} QFF/VFF pts × ${QANTAS_CPP} = ${val:,}"

    # ── Other named points programs (Citi, Amex, ANZ, etc.) ─────────────────
    # e.g. "200,000 Bonus Citi Points", "50,000 Membership Rewards Points"
    m = re.search(
        r"([\d,]+)[^$\n]{0,25}?(?:citi|amex|membership\s+rewards?|rewards?\s+points?|"
        r"frequent\s+flyer|points?\s+bonus)[^$\n]{0,20}?points?",
        t, re.IGNORECASE
    )
    if not m:
        # Also catch "X bonus <brand> points" or "X <brand> bonus points"
        m = re.search(
            r"([\d,]+)[^$\n]{0,30}?\b(?:citi|amex|membership)\b[^$\n]{0,20}?points?",
            t, re.IGNORECASE
        )
    if m:
        pts = _price(m.group(1))
        if pts >= 5000:
            val = int(pts * QANTAS_CPP)   # conservative cross-program estimate
            if val > 0:
                return val, f"{pts:,} reward pts × ${QANTAS_CPP} (est.) = ${val:,}"

    # ── Generic "X Bonus Points" in a CC context ──────────────────────────────
    # e.g. "100,000 Bonus Points" — use Qantas CPP as conservative estimate
    m = re.search(r"([\d,]+)\s+(?:bonus|welcome|signup|sign-up)\s+points?", t, re.IGNORECASE)
    if m:
        pts = _price(m.group(1))
        if pts >= 5000:   # ignore trivial point counts
            val = int(pts * QANTAS_CPP)
            if val > 0:
                return val, f"{pts:,} bonus pts × ${QANTAS_CPP} (est.) = ${val:,}"

    # ── Flybuys / Everyday Rewards ────────────────────────────────────────────
    m = re.search(r"([\d,]+)\s*(?:flybuys|everyday\s+rewards)\s*points?", t, re.IGNORECASE)
    if m:
        pts = _price(m.group(1))
        val = int(pts / 2000 * 10)
        if val > 0:
            return val, f"{pts:,} points → ${val:,} redemption value"

    return None


def _match_cashback(t: str):
    """'X% cashback on $Y spend'."""
    m = re.search(r"([\d.]+)\s*%\s*cash\s*back[^$]*?\$\s*([\d,]+)", t, re.IGNORECASE)
    if m:
        pct, spend = float(m.group(1)), _price(m.group(2))
        val = int(spend * pct / 100)
        if val > 0:
            return val, f"{pct:.0f}% cashback on ${spend:,} = ${val:,}"
    # Flat cashback amount
    m2 = re.search(r"\$\s*([\d,]+)\s*cash\s*back", t, re.IGNORECASE)
    if m2:
        val = _price(m2.group(1))
        if val > 0:
            return val, f"${val:,} cashback offer"
    return None


# ── Two-price fallback ────────────────────────────────────────────────────────

def _match_two_prices(t: str):
    """
    If title has exactly two prices and the larger one is plausibly an RRP.
    Guards against misfiring on:
      - Small bonus tier amounts (e.g. "referrer gets $30, referee gets $20")
      - Tiered payout deals (e.g. "$300 singles / $600 family")
    """
    prices = _all_prices(t)
    if len(prices) < 2:
        return None
    hi, lo = max(prices), min(prices)
    if lo == 0 or hi == lo:
        return None
    savings = hi - lo
    ratio = hi / lo

    # Guard: both amounts are small bonus-sized values (< $150) — likely referral tiers, not prices
    if hi < 150:
        return None

    # Guard: if title contains bonus/referral language, don't treat amounts as was/now
    if re.search(r"\breferr(?:er|ee|al)\b|\bget\s+\$|\breceive\s+\$|\bcash\s+bonus\b|\bedr\b", t, re.IGNORECASE):
        return None

    # Only trust if difference is meaningful and ratio is plausible (10% – 80% off)
    if savings >= 20 and 1.1 <= ratio <= 5.0:
        return savings, f"${hi:,} vs ${lo:,} = ~${savings:,} saving"
    return None


# ── Public API ────────────────────────────────────────────────────────────────

# Sanity cap for regex-derived savings. This needs to allow high-ticket
# consumer categories such as large TVs, appliances, cars, and premium laptops.
MAX_REGEX_SAVINGS = 25000

MATCHERS = [
    ("combined_trade_in", _match_combined_trade_in_discount),
    ("explicit_save",  _match_explicit_save),
    ("spend_get",      _match_spend_get_value),
    ("reward_value",   _match_reward_value),
    ("was_now",        _match_was_now),
    ("rrp",            _match_rrp),
    ("gift_card",      _match_gift_card),
    ("free_bundle",    _match_free_bundle),
    ("points",         _match_points),
    ("cashback",       _match_cashback),
    ("percent_off",    _match_percent_off),
]


def _extract_deal_price(title: str) -> int:
    """
    Best-effort extraction of the actual deal/sale price from the title.

    The deal price is the HEADLINE price — the first significant price that
    appears in the title, before "Delivered/Shipped/@" and outside any
    parenthetical plan/condition text.

    Excludes:
      - $0 (e.g. "$0 delivery", "$0 annual fee")
      - Prices inside parentheses (often RRP, plan rates, conditions)
      - Recurring plan rates ($X/month, $X/28-day, from $X, $X p.a.)
      - Trivially small noise values (< $5)
    """
    # 1. Cut everything from "@" onwards (merchant name + its prices)
    head = re.split(r"\s@\s", title, maxsplit=1)[0]

    # 2. Remove parenthetical content (RRP, plan conditions, "Was $X", etc.)
    head_no_parens = re.sub(r"\([^)]*\)", " ", head)

    # 3. Remove recurring-rate prices: "$30/28-Day", "$30/month", "from $30/mo"
    head_clean = re.sub(
        r"(?:from\s+)?\$\s*[\d,]+(?:\.\d+)?\s*(?:/|p\.?a\.?|per\s+|a\s+)"
        r"\s*(?:\d+[- ]?)?(?:day|days|week|month|mth|year|yr|28[- ]?day)",
        " ",
        head,
        flags=re.IGNORECASE,
    )

    # First price from the cleaned headline (no parens, no plan rates)
    for source in (re.sub(r"\([^)]*\)", " ", head_clean), head_no_parens, head, title):
        prices = [p for p in _all_prices(source) if p >= 5]
        if prices:
            return prices[0]   # headline = FIRST significant price, not lowest
    return 0


def parse_deal_value(deal: dict, live_gift_lookup: bool = False) -> dict:
    """
    Parse savings from title + RSS description.
    Returns {"savings": int, "explanation": str, "deal_price": int}.

    Free gift value is ADDITIVE — if the deal already has a discount saving,
    the free gift value is added on top of it.

    live_gift_lookup=True: query StaticICE for the current market price of any
    detected free gift product. Use this in the main scoring pipeline.
    live_gift_lookup=False (default): fast regex-only path, no network calls.
    """
    title = deal.get("title", "")
    desc  = deal.get("description", "") or ""
    desc_clean = re.sub(r"<[^>]+>", " ", desc)

    # Combined text for free gift lookup (title + desc)
    combined = title + " " + desc_clean

    base_savings = 0
    base_explanation = ""

    # Run broad matchers on the title only. Descriptions often contain price
    # tiers, spend examples, denominations, or comments that are not the deal's
    # saving. Use description only for explicit "save $X" text.
    TITLE_MATCHERS = [(n, m) for n, m in MATCHERS if n != "free_bundle"]
    DESCRIPTION_MATCHERS = [("explicit_save", _match_explicit_save), ("spend_get", _match_spend_get_value)]
    for text_src, matchers in [(title, TITLE_MATCHERS), (desc_clean, DESCRIPTION_MATCHERS)]:
        if not text_src.strip():
            continue
        for name, matcher in matchers:
            result = matcher(text_src)
            if result:
                savings, explanation = result
                if savings > MAX_REGEX_SAVINGS:
                    log.warning(f"  Regex cap: ${savings:,} > ${MAX_REGEX_SAVINGS:,} for '{title[:55]}' [{name}]")
                    continue
                base_savings = savings
                base_explanation = explanation
                break
        if base_savings:
            break

    # Check for free gift value (additive on top of base savings)
    gift_val, gift_desc = 0, ""
    gift_result = _match_free_bundle(combined, use_live_lookup=live_gift_lookup)
    if gift_result:
        gift_val, gift_desc = gift_result
        if gift_val > 3500:   # sanity cap — no single gift >$3,500
            gift_val = 0

    total = base_savings + gift_val

    # Always extract deal price for downstream market comparison
    deal_price = _extract_deal_price(title)

    if total == 0:
        return {"savings": 0, "explanation": "No price pattern found in title", "deal_price": deal_price}

    # Build combined explanation
    parts = []
    if base_explanation:
        parts.append(base_explanation)
    if gift_val:
        parts.append(gift_desc)
    explanation = " + ".join(parts)

    if total > MAX_REGEX_SAVINGS:
        log.warning(f"  Total cap: ${total:,} for '{title[:55]}'")
        total = MAX_REGEX_SAVINGS

    return {"savings": total, "explanation": explanation, "deal_price": deal_price}


def parse_all(deals: list, live_gift_lookup: bool = False) -> list:
    """
    Parse savings for all deals.
    live_gift_lookup=True: queries Claude for free gift prices.
    """
    log.info(f"── Value parsing: {len(deals)} deals (live gift lookup: {live_gift_lookup}) ──")
    for deal in deals:
        result = parse_deal_value(deal, live_gift_lookup=live_gift_lookup)
        deal["savings"]     = result["savings"]
        deal["explanation"] = result["explanation"]
        deal["deal_price"]  = result.get("deal_price", 0)
        status = "✓" if deal["savings"] > 0 else "✗"
        log.info(f"  {status} ${deal['savings']:>5,} — {deal['title'][:60]}")
        if deal["explanation"] and deal["savings"] > 0:
            log.info(f"           {deal['explanation']}")
    found = sum(1 for d in deals if d["savings"] > 0)
    log.info(f"Value parsing: {found}/{len(deals)} deals have extractable savings")
    return deals
