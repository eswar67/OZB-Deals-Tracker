"""
modules/value_parser.py

Fast regex-based savings extractor from OZB deal titles.
No API calls — parses price patterns directly from the title string.

Returns: {"savings": int, "explanation": str, "deal_price": int}

Patterns handled (in priority order):
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

    # Find the first price in title that is less than RRP
    prices = _all_prices(t)
    candidates = [p for p in prices if 0 < p < rrp]
    if not candidates:
        return None
    deal_price = min(candidates)
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

    prices = _all_prices(t)
    if not prices:
        return None

    # The deal price is the smallest price; original = deal / (1 - pct/100)
    deal_price = min(prices)
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
    # Percent off gift cards
    m2 = re.search(r"([\d.]+)\s*%\s*off[^$]*(?:gift\s*card|voucher)", t, re.IGNORECASE)
    if m2:
        pct = float(m2.group(1))
        prices = _all_prices(t)
        if prices:
            face = max(prices)
            savings = int(face * pct / 100)
            if savings > 0:
                return savings, f"{pct:.0f}% off ${face:,} gift card = ${savings:,} saving"
    return None


# ── Known free gift retail prices (AU RRP, conservative) ─────────────────────
# Keyed by lowercase keyword fragments found in deal titles.
# Use the lowest commonly seen street price, not MSRP.
FREE_GIFT_PRICES = {
    # Samsung phones (S-series)
    "galaxy s25 ultra":       1849,
    "galaxy s25+":            1499,
    "galaxy s25":             1249,
    "galaxy s24 ultra":       1649,
    "galaxy s24+":             899,
    "galaxy s24 fe":           799,
    "galaxy s24":             1149,
    "galaxy s23 ultra":       1449,
    "galaxy s23+":            1149,
    "galaxy s23 fe":           649,
    "galaxy s23":              949,
    "s25 ultra":              1849,
    "s25+":                   1499,
    "s25":                    1249,
    "s24 ultra":              1649,
    "s24+":                   1299,
    "s24 fe":                  799,
    "s24":                    1149,
    "s23 ultra":              1449,
    "s23+":                   1149,
    "s23 fe":                  649,
    "s23":                     949,
    # Samsung phones (A-series, Z-series)
    "galaxy z fold 6":        2199,
    "galaxy z flip 6":        1299,
    "galaxy z fold 5":        1999,
    "galaxy z flip 5":        1149,
    "galaxy a55":              649,
    "galaxy a35":              499,
    "galaxy a15":              299,
    # Samsung
    "galaxy buds fe":           99,
    "galaxy buds2 pro":        299,
    "galaxy buds2":            179,
    "galaxy buds live":        149,
    "galaxy buds pro":         249,
    "galaxy buds+":            149,
    "galaxy buds":              99,
    "galaxy watch fe":         299,
    "galaxy watch 7":          449,
    "galaxy watch 6":          399,
    "galaxy watch 5":          349,
    "galaxy watch 4":          299,
    "galaxy watch ultra":      899,
    "galaxy watch":            299,
    "galaxy tab s9 fe":        599,
    "galaxy tab s9":           999,
    "galaxy tab s8":           799,
    "galaxy tab a9":           399,
    "galaxy tab a8":           349,
    "galaxy tab":              349,
    "galaxy fit3":             119,
    "galaxy fit2":              89,
    # Apple
    "airpods pro":             399,
    "airpods max":             899,
    "airpods":                 219,
    "apple watch se":          349,
    "apple watch series 10":   699,
    "apple watch series 9":    649,
    "apple tv":                229,
    "apple pencil":            179,
    "magic keyboard":          199,
    "magic mouse":             129,
    "homepod mini":            149,
    "homepod":                 549,
    # Sony
    "wh-1000xm5":              449,
    "wh-1000xm4":              349,
    "wf-1000xm5":              399,
    "wf-1000xm4":              299,
    "linkbuds s":              199,
    "linkbuds":                249,
    # Bose
    "quietcomfort ultra":      549,
    "quietcomfort 45":         429,
    "quietcomfort earbuds":    349,
    "soundsport":              149,
    # Jabra
    "jabra elite 10":          349,
    "jabra elite 8":           299,
    "jabra elite 4":           149,
    # JBL
    "jbl flip 6":              149,
    "jbl flip 5":              129,
    "jbl charge 5":            229,
    "jbl charge 4":            179,
    "jbl clip 4":               69,
    "jbl go 3":                 49,
    # Garmin
    "garmin forerunner 265":   699,
    "garmin forerunner 255":   549,
    "garmin vivoactive 5":     499,
    "garmin instinct 2":       599,
    # Fitbit
    "fitbit charge 6":         229,
    "fitbit sense 2":          299,
    "fitbit versa 4":          249,
    # Ecovacs / Robot vacuum
    "ecovacs deebot":          499,
    "roomba j7":               699,
    "roomba i7":               599,
    # Storage
    "samsung t7 shield":       149,
    "samsung t7":              129,
    "samsung t9":              179,
    "sandisk extreme ssd":     129,
    # Misc
    "nintendo switch":         469,
    "xbox controller":         109,
    "ps5 controller":          109,
    "nespresso":               199,
    "kindle":                  219,
    "echo dot":                 79,
    "echo":                    149,
    "ring doorbell":           199,
    "philips hue":              89,
    "tile":                     39,
    "airtag":                   45,
    "gopro hero 12":           449,
    "gopro hero 11":           349,
}


def _lookup_free_gift_value(text: str) -> tuple:
    """
    Scan text for known free gift product names.
    Returns (total_value, description_str) or (0, "").
    Sums all matched gifts (handles multiple free items).
    """
    tl = text.lower()
    total = 0
    found = []
    for keyword, price in FREE_GIFT_PRICES.items():
        if keyword in tl:
            total += price
            found.append(f"{keyword.title()} (~${price:,})")
            # Remove matched section to avoid double-counting overlapping keywords
            tl = tl.replace(keyword, "", 1)

    if total > 0:
        return total, "Free gift(s): " + " + ".join(found)
    return 0, ""


def _match_free_bundle(t: str):
    """
    Detect free bundled items in three ways (in priority order):
      1. Explicitly stated value: 'Free X (worth $Y)' / 'Free X valued at $Y'
      2. Known product lookup from FREE_GIFT_PRICES table
      3. Generic 'free' keyword near a price not already the deal price
    """
    # 1. Explicitly stated value
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

    # 2. Only search for free gifts when "free" or "bonus" appears in the text
    if not re.search(r"\bfree\b|\bbonus\b|\bbundled?\b|\bincluded?\b", t, re.IGNORECASE):
        return None

    # 3. Known product lookup
    val, desc = _lookup_free_gift_value(t)
    if val > 0:
        return val, desc

    return None


QANTAS_CPP   = 0.0135   # AUD per Qantas FF point
VELOCITY_CPP = 0.0135   # AUD per Virgin Velocity point


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

# Cap — no single consumer deal saves more than this via regex
MAX_REGEX_SAVINGS = 5000

MATCHERS = [
    ("explicit_save",  _match_explicit_save),
    ("was_now",        _match_was_now),
    ("rrp",            _match_rrp),
    ("gift_card",      _match_gift_card),
    ("free_bundle",    _match_free_bundle),
    ("points",         _match_points),
    ("cashback",       _match_cashback),
    ("percent_off",    _match_percent_off),
    ("two_prices",     _match_two_prices),
]


def _extract_deal_price(title: str) -> int:
    """
    Best-effort extraction of the actual deal/sale price from the title.
    Returns the lowest *positive* dollar amount that looks like a deal price.
    Excludes $0 (e.g. "$0 delivery", "$0 annual fee") and very low noise values.
    Used downstream for market price comparison.
    """
    prices = _all_prices(title)
    # Filter out $0 and trivially small amounts (e.g. "$1 handling fee")
    meaningful = [p for p in prices if p >= 5]
    if not meaningful:
        return 0
    # Heuristic: the lowest meaningful price is the deal price
    # (e.g. "$399 + Delivery ($0 Prime)" → 399, not 0)
    return min(meaningful)


def parse_deal_value(deal: dict) -> dict:
    """
    Parse savings from title + RSS description.
    Returns {"savings": int, "explanation": str, "deal_price": int}.

    Free gift value is ADDITIVE — if the deal already has a discount saving,
    the free gift value is added on top of it.
    """
    title = deal.get("title", "")
    desc  = deal.get("description", "") or ""
    desc_clean = re.sub(r"<[^>]+>", " ", desc)

    # Combined text for free gift lookup (title + desc)
    combined = title + " " + desc_clean

    base_savings = 0
    base_explanation = ""

    # Run non-free-gift matchers first on title, then description
    NON_GIFT_MATCHERS = [(n, m) for n, m in MATCHERS if n != "free_bundle"]
    for text_src in [title, desc_clean]:
        if not text_src.strip():
            continue
        for name, matcher in NON_GIFT_MATCHERS:
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

    # Always check for free gift value (additive on top of base savings)
    gift_val, gift_desc = 0, ""
    gift_result = _match_free_bundle(combined)
    if gift_result:
        gift_val, gift_desc = gift_result
        if gift_val > 2000:   # sanity cap on gift value
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


def parse_all(deals: list) -> list:
    """Parse savings for all deals. O(n) — no API calls."""
    log.info(f"── Value parsing: {len(deals)} deals (regex, no API) ──")
    for deal in deals:
        result = parse_deal_value(deal)
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
