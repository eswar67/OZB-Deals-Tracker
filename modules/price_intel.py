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


def _staticice_query(title: str) -> str:
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


def _parse_staticice_rows(soup: BeautifulSoup, query: str) -> list[dict]:
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


def lookup_staticice(deal: dict) -> dict:
    """
    Search StaticICE for the deal product.

    Adds:
      staticice_url     str  — direct search URL
      staticice_lowest  int  — lowest price found in AUD (0 if not found)
      staticice_label   str  — display string e.g. "$549 at Centrecom"
      staticice_stores  list — [{price, store, store_url}, ...] all matching stores
    """
    title = deal.get("title", "")
    query = _staticice_query(title)

    search_url = f"https://www.staticice.com.au/cgi-bin/search.cgi?q={urllib.parse.quote(query)}&stype=1"
    deal["staticice_url"]    = search_url
    deal["staticice_lowest"] = 0
    deal["staticice_label"]  = ""
    deal["staticice_stores"] = []

    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        entries = _parse_staticice_rows(soup, query)

        if entries:
            best = entries[0]
            deal["staticice_lowest"] = best["price"]
            deal["staticice_label"]  = (
                f"${best['price']:,}" + (f" at {best['store']}" if best["store"] else "")
            )
            deal["staticice_stores"] = entries  # all stores, sorted by price
            log.info(
                f"  StaticICE: {deal['staticice_label']} "
                f"(+{len(entries)-1} more stores) — {deal['title'][:45]}"
            )

    except Exception as e:
        log.debug(f"StaticICE lookup failed for '{title[:40]}': {e}")

    return deal



# ── Market price summary (derived from StaticICE multi-store results) ─────────

def lookup_market_price(deal: dict) -> dict:
    """
    Derive a cross-platform market price from the StaticICE multi-store results
    already fetched by lookup_staticice().

    Requires lookup_staticice() to have run first (it populates staticice_stores).
    Filters out accessories / clearly-wrong results by requiring the market price
    to be within 30%–300% of the deal price (so a $33 ear-cushion kit doesn't
    mask a $399 headphone deal).

    Adds to deal dict:
      market_lowest        int  — lowest comparable price in AUD (0 if not found)
      market_lowest_store  str  — retailer name, e.g. "JB Hi-Fi"
      market_lowest_url    str  — retailer URL if known
      market_alt_stores    list — [{price, store, url}, ...] next 3 cheapest
      market_cheaper       bool — True if market lowest < deal price (set downstream)
      market_saving_vs_deal int — how much cheaper market is (set downstream)
    """
    deal.setdefault("market_lowest",         0)
    deal.setdefault("market_lowest_store",   "")
    deal.setdefault("market_lowest_url",     "")
    deal.setdefault("market_alt_stores",     [])
    deal.setdefault("market_cheaper",        False)
    deal.setdefault("market_saving_vs_deal", 0)

    stores    = deal.get("staticice_stores", [])
    deal_price = deal.get("deal_price", 0)

    if not stores:
        return deal

    # Filter to prices that are plausibly the same product (not accessories)
    if deal_price > 0:
        comparable = [
            s for s in stores
            if deal_price * 0.30 <= s["price"] <= deal_price * 3.0
        ]
    else:
        comparable = stores  # no deal price to compare against, use all

    if not comparable:
        return deal

    best = comparable[0]
    deal["market_lowest"]       = best["price"]
    deal["market_lowest_store"] = best["store"]
    deal["market_lowest_url"]   = best.get("store_url", "")
    deal["market_alt_stores"]   = [
        {"store": s["store"], "price": s["price"], "url": s.get("store_url", "")}
        for s in comparable[1:4]
    ]

    alts_str = ", ".join(
        f"{a['store']} ${a['price']:,}" for a in deal["market_alt_stores"] if a.get("store")
    )
    log.info(
        f"  Market: ${best['price']:,} @ {best['store'] or '?'}"
        + (f" | also: {alts_str}" if alts_str else "")
        + f" — {deal['title'][:45]}"
    )
    return deal


def analyse_all(deals: list[dict], do_staticice: bool = True, do_market: bool = True) -> list[dict]:
    """Run all price intelligence checks on every deal."""
    log.info(f"── Price intelligence: analysing {len(deals)} deals ──")
    for deal in deals:
        detect_cashback(deal)
        detect_price_beat(deal)
        if do_staticice:
            lookup_staticice(deal)
        if do_market:
            lookup_market_price(deal)
    return deals
