"""
modules/price_intel.py
Price intelligence layer.

Functions:
  detect_cashback(deal)       → adds cashback_platform, cashback_pct, cashback_url
  detect_price_beat(deal)     → adds price_beat_stores list
  lookup_staticice(deal)      → adds staticice_url, staticice_lowest (AUD)
  analyse_all(deals)          → runs all checks on each deal, returns enriched list
"""

import re
import logging
import urllib.parse

import requests
from bs4 import BeautifulSoup

# Shared rate limiter — imported from main module at call time to avoid circular import
def _get_limiter():
    try:
        from ozbargain_monitor import _haiku_limiter
        return _haiku_limiter
    except ImportError:
        return None

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    )
}

# ── Cashback detection ────────────────────────────────────────────────────────

# Known merchants and their approximate ShopBack/Cashrewards cashback %
# (conservative estimates — actual rates change; used for flagging only)
CASHBACK_MERCHANTS: dict[str, tuple[str, float]] = {
    # merchant keyword → (platform, approx %)
    "amazon":        ("ShopBack",     5.0),
    "ebay":          ("ShopBack",     1.0),
    "catch":         ("Cashrewards",  3.0),
    "kogan":         ("ShopBack",     3.5),
    "jb hi-fi":      ("Cashrewards",  1.5),
    "jbhifi":        ("Cashrewards",  1.5),
    "harvey norman": ("Cashrewards",  2.0),
    "harveynorman":  ("Cashrewards",  2.0),
    "the good guys": ("Cashrewards",  2.0),
    "myer":          ("ShopBack",     5.0),
    "david jones":   ("ShopBack",     4.0),
    "mwave":         ("Cashrewards",  3.0),
    "centrecom":     ("Cashrewards",  2.0),
    "officeworks":   ("ShopBack",     2.0),
    "bcf":           ("ShopBack",     4.0),
    "rebel":         ("ShopBack",     4.0),
    "nike":          ("ShopBack",     8.0),
    "adidas":        ("ShopBack",     8.0),
    "booking.com":   ("ShopBack",     6.0),
    "hotels.com":    ("Cashrewards",  5.0),
    "agoda":         ("ShopBack",     6.0),
    "expedia":       ("ShopBack",     6.0),
}

# Keywords in deal title/description that hint at cashback being mentioned
CASHBACK_KEYWORDS = [
    "shopback", "cashrewards", "cashback", "cash back",
    "cb bonus", "cb deal", "shopback bonus",
]

# ── Price-beat detection ──────────────────────────────────────────────────────

PRICE_BEAT_STORES = {
    "officeworks": "Officeworks (price beat 5%)",
    "bing lee":    "Bing Lee (price beat)",
    "harvey norman": "Harvey Norman (price beat)",
    "jb hi-fi":    "JB Hi-Fi (price beat)",
    "good guys":   "The Good Guys (price beat)",
    "amazon":      "Amazon (price match)",
}


def detect_cashback(deal: dict) -> dict:
    """
    Adds to deal dict:
      cashback_platform  str   — e.g. "ShopBack", "Cashrewards", or ""
      cashback_pct       float — estimated cashback %, or 0.0
      cashback_url       str   — deep link to ShopBack/Cashrewards (best effort)
      cashback_est_aud   int   — estimated cashback $ (0 if deal price unknown)
    """
    title_lower   = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    merchant_name = deal.get("merchant_name", "").lower()
    external_url  = deal.get("external_url", "").lower()

    # 1) Check if deal title/desc explicitly mentions cashback
    explicitly_mentioned = any(kw in title_lower for kw in CASHBACK_KEYWORDS)

    # 2) Match merchant against known cashback partners
    platform, pct = "", 0.0
    for merchant_key, (plat, rate) in CASHBACK_MERCHANTS.items():
        if (
            merchant_key in title_lower
            or merchant_key in merchant_name
            or merchant_key in external_url
        ):
            platform, pct = plat, rate
            break

    # If not found via merchant DB but mentioned in text, flag generically
    if not platform and explicitly_mentioned:
        platform = "ShopBack/Cashrewards"
        pct = 2.0   # conservative unknown rate

    # Build cashback URL (ShopBack search for simplicity)
    cb_url = ""
    if platform and deal.get("external_url"):
        encoded = urllib.parse.quote(deal["external_url"])
        if "ShopBack" in platform:
            cb_url = f"https://www.shopback.com.au/search?query={urllib.parse.quote(deal.get('merchant_name',''))}"
        else:
            cb_url = f"https://www.cashrewards.com.au/search?query={urllib.parse.quote(deal.get('merchant_name',''))}"

    # Rough cashback $ estimate (only if we can guess the deal price from savings)
    # We approximate: if total cost ≈ savings × (1 / discount fraction)
    # But we don't know deal price reliably, so skip $ estimate
    deal["cashback_platform"] = platform
    deal["cashback_pct"]      = pct
    deal["cashback_url"]      = cb_url

    if platform:
        log.info(
            f"  Cashback: {platform} ~{pct}% — {deal['title'][:50]}"
        )
    return deal


def detect_price_beat(deal: dict) -> dict:
    """
    Adds price_beat_stores: list of store names that may price-beat this deal.
    Only relevant for electronics/appliances categories.
    """
    cats = [c.lower() for c in deal.get("categories", [])]
    title_lower = deal.get("title", "").lower()
    external_lower = deal.get("external_url", "").lower()

    relevant_cats = {"electronics", "computing", "home", "appliances", "gaming", "phones"}
    is_relevant = any(c in relevant_cats for c in cats) or any(
        kw in title_lower for kw in ["laptop", "tv", "phone", "tablet", "monitor", "fridge", "washer", "dryer", "vacuum"]
    )

    stores = []
    if is_relevant:
        for key, label in PRICE_BEAT_STORES.items():
            # Only flag stores that are NOT the source merchant
            if key not in external_lower and key not in deal.get("merchant_name", "").lower():
                stores.append(label)

    deal["price_beat_stores"] = stores[:3]   # top 3
    return deal


def _clean_product_query(title: str) -> str:
    """Build a clean StaticICE search query from a deal title."""
    q = re.sub(r"\([^)]*\)", "", title)            # remove (Was $X) / (RRP $X) etc
    q = re.sub(r"\s*@.*$", "", q)                  # remove everything from @ onwards (merchant)
    q = re.sub(r'["""\'`/\\|:;]', " ", q)          # strip inch marks, quotes, slashes, colons
    q = re.sub(r"\d+(?:\.\d+)?\s*[\"″]", "", q)   # strip size like 10.9" / 14.6"
    q = re.sub(
        r"\$[\d,]+(?:\.\d+)?|[\d]+%|deliver(?:ed|y)?|shipping|"
        r"\bsave\b|\bdeal\b|\boff\b|\bfree\b|australia[n]?|"
        r"\bwas\b|\bnow\b|\bwith\b|\bvia\b|\bplus\b|"
        r"\bwi-?fi\b|\bbluetooth\b|\busb[\w.-]*\b|"    # strip USB specs (USB3.2, USB-C, etc.)
        r"\bgaming hub\b|\bhub\b|\bstation\b|"          # strip generic product category nouns
        r"\bwireless\b|\bheadphones?\b|\bearphones?\b|\bearbuds?\b|"
        r"\bspeaker[s]?\b|\bmonitor[s]?\b|\blaptop[s]?\b|\btablet[s]?\b|"
        r"\bphone[s]?\b|\bcpu\b|\bgpu\b|\bprocessor\b|\bgraphics\b|\bcard\b|"
        r"\bc&c\b|\bin-store\b|\bin store\b|\bdelivered\b",
        " ",
        q,
        flags=re.IGNORECASE,
    )
    # Strip storage/RAM specs like "6GB/128GB", "256GB", "12GB"
    q = re.sub(r"\d+\s*[GT]B(?:\s*/\s*\d+\s*[GT]B)?", "", q, flags=re.IGNORECASE)
    # Strip screen size decimals like "14.6" "10.9" "65.0" (no inch mark needed)
    q = re.sub(r"\b\d{1,3}\.\d\b", " ", q)
    # Strip lone punctuation / single-char tokens left behind (dashes, dots, etc.)
    q = re.sub(r"(?<!\w)[-.](?!\w)", " ", q)
    words = q.split()
    return " ".join(words[:7])  # increased from 5 → 7 so model numbers aren't cut off


def _UNUSED_parse_staticice_rows(soup, query: str) -> list[dict]:  # kept for reference only
    """
    Parse all product+store+price rows from a StaticICE results page.

    StaticICE row structure (2 <td> per <tr>):
      td[0]: "$399.00"
      td[1]: "Bose QuietComfort 45 Headphones - Black<store-name>(states)www.store.com updated:..."
      links: /cgi-bin/redirect.cgi?name=StoreName&linkid=...&newurl=...

    Returns list of {price, store, product, store_url} sorted by price ascending.
    Relevance-filters to rows that match at least 1/3 of query keywords.
    """
    query_words = set(
        w for w in query.lower().split()
        if len(w) > 3 and w not in {
            "with", "from", "that", "this", "plus", "pack",
            "deal", "sale", "save", "shipped", "delivered",
        }
    )
    MIN_OVERLAP = max(1, len(query_words) // 3)

    entries = []
    seen = set()

    for row in soup.find_all("tr"):
        tds = row.find_all("td", recursive=False)
        if len(tds) < 2:
            continue

        # Price is in the first td
        price_text = tds[0].get_text(strip=True)
        m = re.match(r"\$\s*([\d,]+(?:\.\d+)?)", price_text)
        if not m:
            continue
        try:
            price = int(float(m.group(1).replace(",", "")))
        except ValueError:
            continue
        if price < 5 or price > 50000:
            continue

        # Relevance: check td[1] text against query words
        detail_text = tds[1].get_text(separator=" ", strip=True).lower()
        overlap = sum(1 for w in query_words if w in detail_text)
        if overlap < MIN_OVERLAP:
            continue

        # Store name: extract from redirect link name= param
        store = ""
        store_url = ""
        for a in row.find_all("a", href=True):
            href = a["href"]
            nm = re.search(r"name=([^&]+)", href)
            url_m = re.search(r"newurl=([^&]+)", href)
            if nm:
                store = urllib.parse.unquote_plus(nm.group(1))
                if url_m:
                    store_url = urllib.parse.unquote_plus(url_m.group(1))
                break

        # Product name: td[1] text up to the store name
        product_raw = tds[1].get_text(strip=True)
        product = product_raw.replace(store, "").strip()[:80] if store else product_raw[:80]

        entries.append({
            "price":     price,
            "store":     store,
            "product":   product,
            "store_url": store_url,
        })

    entries.sort(key=lambda x: x["price"])

    # Deduplicate: keep only the cheapest listing per store
    seen_stores: dict[str, dict] = {}
    for e in entries:
        store_key = e["store"].lower().strip()
        if store_key not in seen_stores:
            seen_stores[store_key] = e   # already sorted, so first = cheapest
    deduped = list(seen_stores.values())
    deduped.sort(key=lambda x: x["price"])
    return deduped


# ── Claude-based market price lookup ─────────────────────────────────────────
#
# Replaces StaticICE entirely. Claude Haiku knows current AU retail prices for
# popular electronics, appliances, phones, and accessories from training data.
# Results are cached within a run to avoid duplicate API calls.

_market_price_cache: dict[str, dict] = {}   # title → {market_price, note, confidence}


def lookup_market_price_claude(deal: dict, client) -> dict:
    """
    Ask Claude Haiku for the current Australian market price of the product in
    this deal title. Populates:
      market_price      int   — estimated current AU market price (0 = unknown)
      market_note       str   — one-line context ("RRP ~$X at JB Hi-Fi / Harvey Norman")
      market_cheaper    bool  — True if market_price < deal_price (deal may not be a bargain)
      market_saving     int   — deal_price - market_price (negative = deal is cheaper)
    """
    deal.setdefault("market_price",   0)
    deal.setdefault("market_note",    "")
    deal.setdefault("market_cheaper", False)
    deal.setdefault("market_saving",  0)

    title      = deal.get("title", "")
    deal_price = deal.get("deal_price", 0)

    # Only look up product deals (not financial/insurance/gift-card deals)
    skip_signals = ["credit card", "insurance", "cashback", "% p.a.", "gift card",
                    "points", "voucher", "hotel", "flight", "cruise", "superannuation"]
    if any(s in title.lower() for s in skip_signals):
        return deal

    cache_key = title.lower()[:80]
    if cache_key in _market_price_cache:
        cached = _market_price_cache[cache_key]
        deal.update(cached)
        _apply_market_comparison(deal, deal_price)
        return deal

    prompt = f"""You are an Australian retail price expert. For the product in this deal title, state the current typical Australian market price.

Deal: {title}

Reply with EXACTLY: PRICE|NOTE
- PRICE: integer AUD (current street price at major AU retailers like JB Hi-Fi, Harvey Norman, Amazon AU). Use 0 if you cannot determine a reliable price.
- NOTE: one short phrase like "RRP ~$X at JB Hi-Fi / Amazon" or "Market ~$X" or "Unknown"

Examples:
1499|RRP ~$1,499 at JB Hi-Fi / Harvey Norman
449|Market ~$449 at major AU retailers
0|Specialty/niche product — price unknown"""

    try:
        lim = _get_limiter()
        if lim: lim.acquire()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        parts = text.split("|", 1)
        price_str = "".join(c for c in parts[0] if c.isdigit())
        price = int(price_str) if price_str else 0
        note  = parts[1].strip() if len(parts) > 1 else ""

        # Sanity: reject if price is suspiciously low or high
        if price > 0 and (price < 5 or price > 80000):
            price, note = 0, ""

        result = {"market_price": price, "market_note": note}
        _market_price_cache[cache_key] = result
        deal.update(result)
        _apply_market_comparison(deal, deal_price)

        if price > 0:
            log.info(f"  Market price: ${price:,} — {note} | {title[:50]}")

    except Exception as e:
        log.debug(f"Market price lookup failed for '{title[:40]}': {e}")

    return deal


def _apply_market_comparison(deal: dict, deal_price: int):
    """Set market_cheaper and market_saving based on deal_price vs market_price."""
    market = deal.get("market_price", 0)
    if market > 0 and deal_price > 0:
        saving = market - deal_price
        deal["market_saving"]  = saving
        deal["market_cheaper"] = (deal_price > market)   # deal is MORE expensive than market
    else:
        deal["market_saving"]  = 0
        deal["market_cheaper"] = False


def lookup_gift_price_claude(product_name: str, client) -> int:
    """
    Ask Claude Haiku for the current AU retail price of a free gift product.
    Returns integer AUD price, or 0 if unknown.
    Cached within a run.
    """
    key = product_name.lower().strip()
    if key in _market_price_cache:
        return _market_price_cache[key].get("market_price", 0)

    prompt = f"""What is the current Australian retail price for: {product_name}

Reply with EXACTLY: PRICE|SOURCE
- PRICE: integer AUD at major AU retailers (JB Hi-Fi, Harvey Norman, Amazon AU). Use 0 if unknown.
- SOURCE: one short phrase like "JB Hi-Fi ~$X" or "Amazon AU ~$X"

Example: 1299|JB Hi-Fi / Samsung ~$1,299"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )
        text  = msg.content[0].text.strip()
        parts = text.split("|", 1)
        price_str = "".join(c for c in parts[0] if c.isdigit())
        price = int(price_str) if price_str else 0
        note  = parts[1].strip() if len(parts) > 1 else ""
        if price > 0 and (price < 5 or price > 50000):
            price = 0
        _market_price_cache[key] = {"market_price": price, "market_note": note}
        if price > 0:
            log.info(f"  Gift price: '{product_name}' → ${price:,} ({note})")
        return price
    except Exception as e:
        log.debug(f"Gift price lookup failed for '{product_name}': {e}")
        return 0


def analyse_all(deals: list[dict], client=None) -> list[dict]:
    """
    Run all price intelligence checks on every deal.
    - Cashback + price-beat: instant, no API
    - Market price: Claude Haiku in parallel (only for product deals with a deal_price)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    log.info(f"── Price intelligence: {len(deals)} deals ──")

    for deal in deals:
        detect_cashback(deal)
        detect_price_beat(deal)

    if not client:
        log.info("  No Claude client — skipping market price lookup")
        return deals

    # Only look up products where we have a deal price (skip zero-price deals)
    priceable = [d for d in deals if d.get("deal_price", 0) > 0]
    if not priceable:
        return deals

    log.info(f"  Market price lookup: {len(priceable)} deals (Claude Haiku, parallel)")

    def _lookup(deal):
        return lookup_market_price_claude(deal, client)

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_lookup, d): d for d in priceable}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                log.warning(f"Market price error: {e}")

    return deals
