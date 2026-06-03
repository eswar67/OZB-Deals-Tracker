#!/usr/bin/env python3
"""
OzBargain Deal Monitor — Enhanced
Fetches popular deals, scores via Claude, alerts via Gmail, logs to Google Sheets.
Runs once daily at 7:00 PM via launchd (com.ozbargain.monitor).

Pipeline:
  fetch_all_deals()
  → filter_deals()              # votes / comments / clicks thresholds (no age limit)
  → keyword_filter()            # blocklist pre-filter
  → oos_filter()                # drop expired/OOS by title signals
  → price_intel.analyse()       # cashback detection, price-beat hints, StaticICE lookup
  → score_deals()               # two-pass Claude: value calculation then quality score
  → prefs.match_all()           # relevance tagging against user-prefs.json
  → top_deals filter            # score≥MIN_SCORE + savings≥MIN_SAVINGS ($200)
  → flash deal flagging
  → fetch_financial_deals()     # banking, CC, insurance — tag feeds, no age limit
  → fetch_travel_deals()        # flights, hotels, cruises — no age limit
  → fetch_lifestyle_deals()     # food/groceries + home/appliances — top 5 each
  → review_and_fix_deals()      # single Claude Sonnet pre-send quality pass
  → email_builder.build()       # rich HTML deal card email
  → send_gmail_alert()
"""

import os
import time
import threading
import base64
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from dotenv import load_dotenv, dotenv_values
import anthropic

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Local modules ─────────────────────────────────────────────────────────────
from modules.storage        import is_flash_deal   # filter_unsent/mark_sent removed — no deduplication
from modules.price_intel    import analyse_all
from modules.prefs          import match_all
from modules.email_builder  import build_email_html
from modules.value_parser   import parse_all as parse_deal_values
from modules.personal_score import score_all_personal
from modules.life_events    import get_life_event_alerts
from modules.money_audit    import get_money_audit
from modules.travel_arb     import get_travel_arb
from modules.negotiation    import add_negotiation_scripts
from modules.briefing       import build_briefing

# ── Config ────────────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_env_path)
# Fallback: manually inject any keys load_dotenv missed (handles UTF-8 comment lines)
for _k, _v in dotenv_values(_env_path).items():
    if _v is not None and not os.environ.get(_k):
        os.environ[_k] = _v

FEED_URL           = "https://www.ozbargain.com.au/deals/feed"
FINANCIAL_FEED_URL = "https://www.ozbargain.com.au/cat/financial/feed"
TRAVEL_FEED_URL    = "https://www.ozbargain.com.au/cat/travel/feed"

# OZB tag feeds to supplement the financial category feed.
# The financial RSS is NOT paginated (all pages return identical content),
# so we skip pagination and instead pull from targeted tag feeds to maximise
# CC/points deal coverage.
FINANCIAL_TAG_FEEDS = [
    # Credit cards & points
    "https://www.ozbargain.com.au/tag/credit-cards/feed",
    "https://www.ozbargain.com.au/tag/frequent-flyer/feed",
    "https://www.ozbargain.com.au/tag/qantas-points/feed",
    "https://www.ozbargain.com.au/tag/velocity-points/feed",
    # Lending & banking
    "https://www.ozbargain.com.au/tag/home-loan/feed",
    "https://www.ozbargain.com.au/tag/cashback/feed",
    # Insurance (all types)
    "https://www.ozbargain.com.au/tag/health-insurance/feed",
    "https://www.ozbargain.com.au/tag/car-insurance/feed",
    "https://www.ozbargain.com.au/tag/home-insurance/feed",
    "https://www.ozbargain.com.au/tag/life-insurance/feed",
    "https://www.ozbargain.com.au/tag/pet-insurance/feed",
    "https://www.ozbargain.com.au/tag/contents-insurance/feed",
    "https://www.ozbargain.com.au/tag/landlord-insurance/feed",
    "https://www.ozbargain.com.au/tag/income-protection/feed",
]

# Food & grocery feeds
FOOD_FEEDS = [
    "https://www.ozbargain.com.au/cat/groceries/feed",
    "https://www.ozbargain.com.au/tag/supermarket/feed",
    "https://www.ozbargain.com.au/tag/coles/feed",
    "https://www.ozbargain.com.au/tag/woolworths/feed",
    "https://www.ozbargain.com.au/tag/meal-kit/feed",
    "https://www.ozbargain.com.au/cat/dining-takeaway/feed",
]

# Home & appliances feeds
HOME_APPLIANCE_FEEDS = [
    "https://www.ozbargain.com.au/tag/whitegoods/feed",
    "https://www.ozbargain.com.au/tag/fridge/feed",
    "https://www.ozbargain.com.au/tag/washing-machine/feed",
    "https://www.ozbargain.com.au/tag/vacuum/feed",
    "https://www.ozbargain.com.au/tag/air-fryer/feed",
    "https://www.ozbargain.com.au/tag/kitchen/feed",
    "https://www.ozbargain.com.au/tag/appliances/feed",
    "https://www.ozbargain.com.au/cat/home-garden/feed",
]

# Additional category feeds — previously untracked, all $200+ filtered
COMPUTING_FEEDS = [
    "https://www.ozbargain.com.au/cat/computing/feed",
]

GAMING_FEEDS = [
    "https://www.ozbargain.com.au/cat/gaming/feed",
]

MOBILE_FEEDS = [
    "https://www.ozbargain.com.au/cat/mobile/feed",
]

ELECTRICAL_FEEDS = [
    "https://www.ozbargain.com.au/cat/electrical-electronics/feed",
]

AUTOMOTIVE_FEEDS = [
    "https://www.ozbargain.com.au/cat/automotive/feed",
]

HEALTH_BEAUTY_FEEDS = [
    "https://www.ozbargain.com.au/cat/health-beauty/feed",
]

ENTERTAINMENT_FEEDS = [
    "https://www.ozbargain.com.au/cat/entertainment/feed",
]

INTERNET_FEEDS = [
    "https://www.ozbargain.com.au/cat/internet/feed",
]

TOYS_FEEDS = [
    "https://www.ozbargain.com.au/cat/toys-kids/feed",
]

PETS_FEEDS = [
    "https://www.ozbargain.com.au/cat/pets/feed",
]

# Points valuations (AUD per point)
QANTAS_CPP   = 0.0135   # Qantas Frequent Flyer
VELOCITY_CPP = 0.0135   # Virgin Velocity
MIN_VOTES      = int(os.getenv("MIN_VOTES",    "30"))
MIN_COMMENTS   = int(os.getenv("MIN_COMMENTS", "10"))
MIN_CLICKS     = int(os.getenv("MIN_CLICKS",   "200"))
MAX_AGE_HOURS  = 999999  # No age limit — fetch all available deals
MIN_SCORE      = int(os.getenv("MIN_SCORE",    "7"))
MIN_SAVINGS    = int(os.getenv("MIN_SAVINGS",  "200"))

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
GMAIL_TO           = os.getenv("GMAIL_TO")   # comma-separated for multiple recipients
GMAIL_CC           = os.getenv("GMAIL_CC")   # optional CC recipients, comma-separated
TOKEN_FILE         = os.getenv("TOKEN_FILE", "token.json")
CREDENTIALS_FILE   = os.getenv("CREDENTIALS_FILE", "credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]

OZB_NS = "https://www.ozbargain.com.au"

# ── Claude API rate limiter ───────────────────────────────────────────────────
# Haiku limit: 50 req/min. We cap at 40 to leave 20% headroom.
# All parallel Claude calls share this single limiter.

class _RateLimiter:
    """Token-bucket rate limiter — thread-safe."""
    def __init__(self, max_per_minute: int):
        self._interval = 60.0 / max_per_minute   # seconds between requests
        self._lock     = threading.Lock()
        self._next_ok  = 0.0                      # earliest time next call is allowed

    def acquire(self):
        with self._lock:
            now  = time.monotonic()
            wait = self._next_ok - now
            if wait > 0:
                time.sleep(wait)
            self._next_ok = time.monotonic() + self._interval

_haiku_limiter = _RateLimiter(max_per_minute=40)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Google auth ───────────────────────────────────────────────────────────────

def get_google_creds() -> Credentials:
    token_path = Path(TOKEN_FILE)
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing Google OAuth token…")
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        else:
            raise RuntimeError(
                f"No valid Google credentials found. "
                f"Run setup_oauth.py first to generate {TOKEN_FILE}."
            )
    return creds

# ── Feed fetching & parsing ───────────────────────────────────────────────────

def fetch_feed(url: str) -> str:
    r = requests.get(url, timeout=30, headers={"User-Agent": "OzBargainMonitor/2.0"})
    r.raise_for_status()
    return r.text


def fetch_all_deals() -> list[dict]:
    """Paginate OzBargain RSS (sorted by hot score, not date).

    Keeps fetching until MAX_CONSECUTIVE_OLD_PAGES consecutive pages have
    zero deals inside the MAX_AGE_HOURS window.
    """
    from email.utils import parsedate_to_datetime

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    # Cap at 50 pages — OZB RSS naturally runs out of content and the
    # MAX_CONSECUTIVE_OLD_PAGES guard will stop early anyway
    max_pages = 50
    MAX_CONSECUTIVE_OLD_PAGES = 3

    all_deals = []
    consecutive_old = 0
    page = 0

    while page < max_pages:
        url = f"{FEED_URL}?page={page}"
        log.info(f"Fetching page {page}/{max_pages-1}: {url}")
        try:
            xml_text = fetch_feed(url)
        except Exception as e:
            log.warning(f"Failed to fetch page {page}: {e}")
            break

        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        items = channel.findall("item")

        if not items:
            log.info(f"Empty page {page} — stopping")
            break

        page_hits = 0
        for item in items:
            def text(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            meta = item.find(f"{{{OZB_NS}}}meta")
            meta_attr = meta.attrib if meta is not None else {}

            pub_raw = text("pubDate")
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

            if pub_dt >= cutoff:
                page_hits += 1
                all_deals.append({
                    "title":        text("title"),
                    "link":         text("link"),
                    "external_url": meta_attr.get("url", ""),
                    "description":  text("description"),
                    "pubDate":      pub_dt,
                    "votes":        int(meta_attr.get("votes-pos",    0)),
                    "comments":     int(meta_attr.get("comment-count", 0)),
                    "clicks":       int(meta_attr.get("click-count",  0)),
                    "expiry_label": _parse_expiry(meta_attr),
                })

        log.info(f"  Page {page}: {len(items)} items, {page_hits} in window, total={len(all_deals)}")

        if page_hits == 0:
            consecutive_old += 1
            if consecutive_old >= MAX_CONSECUTIVE_OLD_PAGES:
                log.info(f"{MAX_CONSECUTIVE_OLD_PAGES} consecutive empty pages — stopping")
                break
        else:
            consecutive_old = 0

        page += 1

    # Deduplicate by link
    seen = set()
    unique = []
    for d in all_deals:
        if d["link"] not in seen:
            seen.add(d["link"])
            unique.append(d)

    log.info(f"Fetched {len(unique)} unique deals across {page} page(s) (no age limit)")
    return unique

# ── Threshold filter ──────────────────────────────────────────────────────────

def filter_deals(deals: list[dict]) -> list[dict]:
    filtered = [
        d for d in deals
        if d["votes"]    >= MIN_VOTES
        and d["comments"] >= MIN_COMMENTS
        and d["clicks"]   >= MIN_CLICKS
    ]
    log.info(
        f"{len(filtered)} deals pass threshold filters "
        f"(votes≥{MIN_VOTES}, comments≥{MIN_COMMENTS}, clicks≥{MIN_CLICKS})"
    )
    return filtered

# ── Keyword pre-filter ────────────────────────────────────────────────────────

BLOCKLIST = [
    # Food & drink
    "pizza", "burger", "coffee", "cafe", "restaurant", "food", "meal", "drink",
    "domino", "hungry jack", "mcdonald", "kfc", "subway", "grill'd", "nandos",
    "menulog", "deliveroo", "uber eat", "doordash", "gelato", "boba", "bubble tea",
    "chocolate", "snack", "beer", "wine", "spirits", "alcohol",
    # Haircuts / beauty / personal services
    "haircut", "hair cut", "salon", "barber", "beauty", "massage", " spa ", "spa@",
    "day spa", "facial", "nail", "wax", "eyelash", "tattoo",
    # Petrol
    "cents per litre", "c/l fuel", "cents/litre",
    # Low-value subscriptions & trials
    "free trial", "7-day", "14-day", "30-day free",
    "spotify", "netflix free", "disney+ free", "apple tv free",
    # Entertainment tickets
    "movie ticket", "cinema ticket", "event ticket", "concert ticket",
    # Gambling
    " bet ", "sportsbet", "odds", "casino", "punt",
    # Charity
    "donate", "charity", "fundrais",
    # Vague discounts
    "% off sitewide", "% off storewide",
    # Cashback portals — these are financial/cashback deals, not product deals
    # (they appear on the main feed but have no computable product savings)
    "@ topcashback", "@ shopback", "@ cashrewards",
    "% cashback", "cashback on", "cashback for",
    # Freebies with no dollar value (points/loyalty promos)
    "free - ", "@ steam", "freebie",
    # Crypto / NFT / speculative
    "bitcoin", "ethereum", "crypto", "nft ", "web3",
    # Referral-only deals (no product)
    "referrer gets", "referee gets",
]

ALLOWLIST_OVERRIDE = [
    "free tv", "free laptop", "free phone", "free tablet", "free headphone",
    "free appliance", "free monitor",
]


def keyword_filter(deals: list[dict]) -> list[dict]:
    kept, dropped = [], []
    for d in deals:
        title_lower = d["title"].lower()
        if any(a in title_lower for a in ALLOWLIST_OVERRIDE):
            kept.append(d)
            continue
        matched = next((b for b in BLOCKLIST if b in title_lower), None)
        if matched:
            dropped.append((d["title"], matched))
        else:
            kept.append(d)

    if dropped:
        log.info(f"Keyword filter dropped {len(dropped)} deals:")
        for title, reason in dropped[:10]:
            log.info(f"  ✗ [{reason}] {title[:70]}")
        if len(dropped) > 10:
            log.info(f"  … and {len(dropped)-10} more")

    log.info(f"{len(kept)} deals remain after keyword filter ({len(dropped)} dropped)")
    return kept


# ── Out-of-stock / expired filter ────────────────────────────────────────────
# Since OZB page scraping is blocked by Cloudflare, detect OOS from the RSS
# title itself. OZB posters often update titles when deals expire.

OOS_TITLE_SIGNALS = [
    "[expired]", "[out of stock]", "[oos]", "[sold out]", "[ended]",
    "(expired)", "(out of stock)", "(oos)", "(sold out)", "(ended)",
    "out of stock", "sold out", "no longer available", "deal expired",
    "now expired", "stock cleared", "all sold",
]


def oos_filter(deals: list[dict]) -> list[dict]:
    """Drop deals whose titles indicate they are expired or out of stock."""
    kept, dropped = [], []
    for d in deals:
        title_lower = d["title"].lower()
        signal = next((s for s in OOS_TITLE_SIGNALS if s in title_lower), None)
        if signal:
            dropped.append((d["title"], signal))
        else:
            kept.append(d)

    if dropped:
        log.info(f"OOS filter dropped {len(dropped)} deal(s):")
        for title, reason in dropped[:5]:
            log.info(f"  ✗ [{reason}] {title[:70]}")

    log.info(f"{len(kept)} deals remain after OOS filter ({len(dropped)} dropped)")
    return kept


# ── Claude scoring — two-pass ─────────────────────────────────────────────────

def calculate_value(client: anthropic.Anthropic, deal: dict) -> dict:
    """Pass 1 — AUD value calculation using Sonnet for better product knowledge."""
    prompt = f"""You are an expert Australian deal value calculator with deep knowledge of Australian retail prices.

Deal title: {deal['title']}
Votes: {deal['votes']} | Comments: {deal['comments']} | Clicks: {deal['clicks']}

DEAL TYPE — identify and apply the correct method:

PRICE DISCOUNT (most common)
  Extract the deal price from the title (e.g. "$X" or "for $X").
  Savings = RRP − deal_price.
  Priority for RRP:
    A. Title states "was $X", "RRP $X", or "save $X" → use that figure directly.
    B. Major brand product (Apple, Samsung, Sony, LG, Dyson, Bose, Garmin, Denon,
       Lenovo, Dell, HP, ASUS, Acer, MSI, Nikon, Canon, DJI, GoPro, Breville,
       KitchenAid, Roomba, Ecovacs, Shark, Philips, Jabra, Sennheiser, JBL) →
       USE your training knowledge of the Australian retail price. Be decisive.
       Compare to the lowest known AU retail price (not inflated MSRP).
    C. Unknown/no-name/AliExpress/grey-market → return 0.

POINTS & REWARDS
  Qantas FF pts: ×$0.014 | Velocity: ×$0.008 | Bank pts: ×$0.006
  Flybuys/Everyday Rewards: 2,000pts = $10

GIFT CARDS / STORE CREDIT AT DISCOUNT
  Value = face value − purchase price

CASHBACK
  Value = purchase amount × cashback %

BUNDLED FREE ITEMS
  Value = standalone retail price of all free items combined

FREE / DISCOUNTED SUBSCRIPTION
  Value = (normal monthly price − deal price) × months covered (cap 12 months)

SANITY CHECK:
  - Max saving for a consumer deal: $3,000 AUD
  - Max for large points bonuses: $7,000 AUD
  - The price in the title is the PURCHASE PRICE, not the saving
  - If calculated saving > $3,000, you've made an error → return 0

Reply with EXACTLY one line: VALUE|EXPLANATION
- VALUE: integer AUD (no $ sign, no commas, no decimals)
- EXPLANATION: one concise sentence showing the calculation (max 20 words)

Examples:
601|Stated RRP $1,999 − deal $1,398 = $601
250|AU RRP ~$1,199 − deal $949 = $250 (Denon AVR)
1260|90,000 Qantas pts × $0.014 = $1,260
220|Sony WH-1000XM5 AU RRP ~$499 − deal $279 = $220
0|No-name import, no reliable AU price"""

    MAX_SAVINGS_CAP = 7000

    try:
        _haiku_limiter.acquire()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        response = msg.content[0].text.strip()
        # Only take the first 30 chars of part[0] — prevents digit extraction from
        # grabbing a multi-digit number embedded elsewhere in a malformed response
        parts = response.split("|", 1)
        raw_value_str = parts[0][:30]
        digit_str = "".join(c for c in raw_value_str if c.isdigit())
        savings = int(digit_str) if digit_str else 0
        explanation = parts[1].strip() if len(parts) > 1 else ""

        # Hard sanity cap — enforce unconditionally
        if savings > MAX_SAVINGS_CAP:
            log.warning(
                f"  Savings ${savings:,} exceeds cap ${MAX_SAVINGS_CAP:,} for "
                f"'{deal['title'][:50]}' — setting to 0. Raw response: {response[:80]}"
            )
            savings, explanation = 0, "Savings figure unreliable — could not verify"

        return {"savings": savings, "explanation": explanation}
    except Exception as e:
        log.warning(f"Value calc failed for '{deal['title']}': {e}")
        return {"savings": 0, "explanation": ""}


def assign_score(client: anthropic.Anthropic, deal: dict) -> dict:
    """Pass 2 — accessibility/quality score with trust % breakdown (Haiku).
    Returns {score, score_reason, trust_pct, trust_barriers}
    """
    prompt = f"""You are an Australian deal quality scorer. The dollar value has already been calculated.

Deal: {deal['title']}
Confirmed value: ${deal['savings']} AUD
How: {deal['explanation']}
Votes: {deal['votes']} | Comments: {deal['comments']} | Clicks: {deal['clicks']}

Score this deal 1-10 on ACCESSIBILITY and RELIABILITY:
10 = Anyone can claim, value guaranteed, no hoops
8-9 = Minor requirement (specific bank account, free to get)
6-7 = Moderate effort (CBA Yello customer, trade-in needed)
4-5 = Significant hoops (limited to 200 people, lottery, requires existing product)
1-3 = Very restricted, highly targeted, or large upfront spend required

Also list the main BARRIERS to claiming this deal (max 2, comma-separated). Use phrases like:
"New customers only", "Requires trade-in", "Limited stock", "CBA Yello required",
"Min spend $X", "Specific state only", "Students only", "Existing product needed"
Use "None" if no barriers.

Reply with EXACTLY: SCORE|REASON|BARRIERS
Example: 6|Requires existing CBA account which is free to open|CBA Yello required,New customers only"""

    try:
        _haiku_limiter.acquire()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        response = msg.content[0].text.strip()
        parts = response.split("|")
        score    = max(1, min(10, int("".join(c for c in (parts[0] if parts else "0") if c.isdigit()) or "0")))
        reason   = parts[1].strip() if len(parts) > 1 else ""
        barriers_raw = parts[2].strip() if len(parts) > 2 else ""
        barriers = [] if barriers_raw.lower() in ("none", "") else [b.strip() for b in barriers_raw.split(",") if b.strip()]
        trust_pct = score * 10  # 1→10%, 10→100%
        return {"score": score, "score_reason": reason, "trust_pct": trust_pct, "trust_barriers": barriers}
    except Exception as e:
        log.warning(f"Scoring failed for '{deal['title']}': {e}")
        return {"score": 0, "score_reason": "", "trust_pct": 0, "trust_barriers": []}


def score_deals(deals: list[dict]) -> list[dict]:
    """
    Step 1 — regex value parsing (no API, instant).
    Step 2 — Claude Haiku accessibility score (only for deals passing MIN_SAVINGS).
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Step 1: parse savings from title — only for deals not yet valued.
    # Do NOT overwrite savings already set by the StaticICE market-price
    # comparison in main() (step 7c); that data is more accurate than title regex.
    from modules.value_parser import parse_deal_value as _pdv
    for d in deals:
        if d.get("savings", 0) == 0:
            result = _pdv(d, live_gift_lookup=True)
            d.update(result)

    value_passed = [d for d in deals if d["savings"] >= MIN_SAVINGS]
    dropped = len(deals) - len(value_passed)
    log.info(f"Value filter: {len(value_passed)} pass (≥${MIN_SAVINGS}), {dropped} dropped")

    if not value_passed:
        return []

    # Step 2: Haiku accessibility score — parallel (I/O bound)
    log.info("── Scoring quality/accessibility (Haiku, parallel) ──")
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    def _score_one(deal):
        return deal, assign_score(client, deal)

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_score_one, d): d for d in value_passed}
        for f in _as_completed(futures):
            try:
                deal, result = f.result()
                deal["score"]          = result["score"]
                deal["score_reason"]   = result["score_reason"]
                deal["trust_pct"]      = result["trust_pct"]
                deal["trust_barriers"] = result["trust_barriers"]
                log.info(f"  [{deal['score']}/10 trust={result['trust_pct']}%] ${deal['savings']:,} — {deal['title'][:50]}")
            except Exception as e:
                log.warning(f"Scoring error: {e}")

    return value_passed


# ── Deal type classifier ─────────────────────────────────────────────────────

# Hard CC phrases — checked before banking signals so "balance transfer" isn't
# swallowed by the "p.a." banking catch
CC_HARD = [
    "credit card", "credit-card",
    "balance transfer",
    "0% purchase", "0% on purchases",
    "complimentary lounge", "airport lounge pass",
    # Bank card product names (always CC, never travel)
    "altitude black", "altitude platinum", "altitude rewards",
    "qff/vff", "qff points", "vff points",
    "frequent flyer black", "frequent flyer platinum", "frequent flyer card",
    "rewards signature", "rewards platinum", "rewards black",
    "cashback card", "no annual fee card",
    "anz black", "anz platinum", "anz rewards",
    "nab rewards", "nab qantas", "nab flybuys",
    "cba awards", "commbank awards", "smart awards",
    "westpac black", "westpac platinum", "westpac altitude",
    "st.george amplify", "bank of melbourne amplify", "banksa amplify",
    "macquarie black", "macquarie platinum",
    "citibank rewards", "citi rewards", "citi prestige", "citi premier",
    "amex explorer", "amex platinum", "amex velocity", "amex qantas",
    "american express", "bankwest more rewards", "bankwest zero",
    "virgin money flyer", "virgin australia velocity",
    "hsbc star alliance", "hsbc everyday",
]

# Signals to exclude from financial section entirely.
# Health insurance deals WITH cashback/bonus ARE included (fetched via tag feed).
# Only exclude government rebates / non-financial noise.
HEALTH_INSURANCE_SIGNALS = [
    # Government rebates — not banking/insurance products
    "rego rebate", "car rego", "registration rebate",
    "service victoria", "service nsw", "service qld",
    "government rebate", "govt rebate", "state government",
    "energy bill relief", "cost of living payment",
]

# Banking signals — win over soft CC signals (catches HISA, savings accounts, etc.)
BANKING_SIGNALS = [
    "savings account", "saver account", "save account", "saving account",
    "high interest", "hisa", "% p.a.", "p.a. interest", "interest on balance",
    "interest rate",
    "home loan", "mortgage", "refinan", "offset account",
    "term deposit", "superannuation", "smsf",
    "share trading", "brokerage", "etf ", " asx ", "invest",
    "margin loan", "personal loan", "car loan", "business account",
    "transaction account", "everyday account",
    "insurance",
    "bonus cash", "cash bonus",
]

# Soft CC signals — only checked after banking signals are cleared
CC_SOFT = [
    "sign-up bonus", "signup bonus", "welcome bonus",
    "annual fee",
    "qantas points", "velocity points", "flybuys points", "rewards points",
    "earn points", "bonus points", "frequent flyer", "ff points",
    "cashback card", "interest free card",
    "card spend", "minimum spend",
    "card membership", "card holder",
    "travel credit",
]

TRAVEL_KEYWORDS = [
    "flight", "airfare", "airline", "return to", "rtn to", "rtn flight",
    " rtn ", "fly ", " fly ",
    "qantas", "virgin australia", "jetstar", "rex airline", "tigerair",
    "emirates", "singapore airlines", "cathay", "united airlines", "thai airways",
    "royal brunei", "air new zealand", "malaysia airlines", "lufthansa",
    # Additional airlines
    "fiji airways", "air pacific", "scoot", "airasia", "air asia",
    "korean air", "japan airlines", "ana ", " ana ", "eva air",
    "china southern", "air china", "china eastern", "hainan airlines",
    "turkish airlines", "etihad", "gulf air", "air india",
    "philippine airlines", "garuda", "lion air", "batik air",
    "air tahiti", "air vanuatu", "solomon airlines", "papua new guinea airlines",
    "hotel", "resort", "motel", "accommodation", "airbnb", "booking.com",
    "trivago", "agoda", "expedia", "hotels.com", "wotif",
    "cruise", "carnival", "royal caribbean", "p&o cruise",
    "holiday package", "holiday park", "klook", "viator",
    "travel insurance", "lounge access", "airport lounge",
]


def classify_deal(deal: dict) -> str:
    """
    Return 'credit_card', 'travel', or 'banking' based on title keywords.

    Priority order:
      1. Hard CC phrases  → 'credit_card'  (balance transfer, credit card — unambiguous)
      2. Banking signals  → 'banking'      (savings accounts, HISA, p.a. interest rates)
      3. Soft CC signals  → 'credit_card'  (points bonus, annual fee, sign-up)
      4. Travel keywords  → 'travel'
      5. Default          → 'banking'
    """
    t = deal.get("title", "").lower()

    if any(k in t for k in CC_HARD):
        return "credit_card"

    if any(k in t for k in BANKING_SIGNALS):
        return "banking"

    if any(k in t for k in CC_SOFT):
        return "credit_card"

    if any(k in t for k in TRAVEL_KEYWORDS):
        return "travel"

    return "banking"


# ── Financial deals ───────────────────────────────────────────────────────────

# Relaxed thresholds for financial category (fewer votes/clicks than product deals)
FIN_MIN_VOTES    = 10
FIN_MIN_COMMENTS = 3
FIN_MIN_CLICKS   = 30
FIN_MIN_SCORE    = 6
FIN_MIN_SAVINGS  = int(os.getenv("FIN_MIN_SAVINGS", "200"))   # min $ value for financial deals
TRAVEL_MIN_SAVINGS = int(os.getenv("TRAVEL_MIN_SAVINGS", "200"))  # min $ value for travel deals


def _parse_expiry(meta_attr: dict) -> str:
    """Extract expiry datetime string from ozb:meta and return a human-readable label."""
    raw = meta_attr.get("expiry", "")
    if not raw:
        return ""
    try:
        from datetime import datetime as _dt
        # ISO format: 2026-06-10T23:59:00+10:00
        exp = _dt.fromisoformat(raw)
        now = datetime.now(exp.tzinfo)
        delta = exp - now
        days  = delta.days
        hours = int(delta.total_seconds() / 3600)
        if delta.total_seconds() < 0:
            return "Expired"
        elif hours < 2:
            return f"⏰ Expires <2h"
        elif hours < 24:
            return f"⏰ Expires today ({exp.strftime('%H:%M')})"
        elif days == 1:
            return f"⏰ Expires tomorrow"
        elif days <= 7:
            return f"⏰ Expires {exp.strftime('%a %d %b')}"
        else:
            return f"Expires {exp.strftime('%d %b')}"
    except Exception:
        return ""


def _parse_feed_items(xml_text: str, cutoff: datetime, source_label: str) -> list[dict]:
    """Parse RSS XML and return deal dicts for items newer than cutoff."""
    from email.utils import parsedate_to_datetime

    root    = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []
    items  = channel.findall("item")
    result = []
    for item in items:
        def text(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        meta      = item.find(f"{{{OZB_NS}}}meta")
        meta_attr = meta.attrib if meta is not None else {}

        pub_raw = text("pubDate")
        try:
            pub_dt = parsedate_to_datetime(pub_raw)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pub_dt = datetime.now(timezone.utc)

        if pub_dt < cutoff:
            continue

        result.append({
            "title":        text("title"),
            "link":         text("link"),
            "external_url": meta_attr.get("url", ""),
            "pubDate":      pub_dt,
            "votes":        int(meta_attr.get("votes-pos",    0)),
            "comments":     int(meta_attr.get("comment-count", 0)),
            "clicks":       int(meta_attr.get("click-count",  0)),
            "expiry_label": _parse_expiry(meta_attr),
            "is_financial": True,
        })
    log.info(f"  {source_label}: {len(items)} items, {len(result)} in window")
    return result


def fetch_financial_deals() -> list[dict]:
    """
    Fetch financial deals from:
      1. OZB financial category feed (1 page only — OZB's financial RSS is NOT
         paginated; all pages return identical content)
      2. Targeted tag feeds for CC/points/home-loan to maximise coverage of
         deals that predate the rolling financial feed window
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    seen   = set()
    deals  = []

    # Fetch all financial feeds in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed as _asc
    import threading
    _seen_lock = threading.Lock()

    all_feed_urls = [FINANCIAL_FEED_URL] + FINANCIAL_TAG_FEEDS

    def _fetch_fin_feed(url):
        xml = fetch_feed(url)
        label = "financial/feed" if url == FINANCIAL_FEED_URL else url.split("/")[-2]
        return _parse_feed_items(xml, cutoff, label)

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_fin_feed, u): u for u in all_feed_urls}
        for f in _asc(futures):
            url = futures[f]
            try:
                items = f.result()
                added = 0
                with _seen_lock:
                    for d in items:
                        if d["link"] not in seen:
                            seen.add(d["link"])
                            deals.append(d)
                            added += 1
                if added:
                    log.info(f"  {url.split('/')[-2]}: +{added} unique deals")
            except Exception as e:
                log.warning(f"Feed {url} failed: {e}")

    log.info(f"Financial feed total: {len(deals)} unique deals (no age limit)")
    return deals


def filter_financial_deals(deals: list[dict]) -> list[dict]:
    """Apply relaxed thresholds and OOS filter to financial deals."""
    kept   = [
        d for d in deals
        if d["votes"]    >= FIN_MIN_VOTES
        and d["comments"] >= FIN_MIN_COMMENTS
        and d["clicks"]   >= FIN_MIN_CLICKS
    ]
    log.info(f"Financial threshold filter: {len(kept)}/{len(deals)} passed")

    # OOS filter
    kept2 = []
    for d in kept:
        tl = d["title"].lower()
        if not any(s in tl for s in OOS_TITLE_SIGNALS):
            kept2.append(d)
    log.info(f"Financial OOS filter: {len(kept2)}/{len(kept)} passed")
    return kept2


def calculate_financial_value(client: anthropic.Anthropic, deal: dict) -> dict:
    """Value calculator tuned for financial/banking deals."""
    prompt = f"""You are an expert Australian financial deal analyser.

Deal title: {deal['title']}
Votes: {deal['votes']} | Comments: {deal['comments']} | Clicks: {deal['clicks']}

Calculate the TOTAL REALISTIC DOLLAR VALUE this deal offers a new customer. Use these methods:

BANK ACCOUNT BONUS
  Value = stated cash bonus (e.g. "$200 bonus" → 200)

CREDIT CARD SIGN-UP BONUS (points)
  Qantas FF pts: ×$0.0135 | Velocity pts: ×$0.0135 | Other: ×$0.006
  Cap at $1,500 unless bonus is explicitly > 100,000 pts

ANNUAL FEE WAIVER
  Value = annual fee waived (first year)

BALANCE TRANSFER / REFINANCE
  Only calculate if a rate and balance are stated. Otherwise return 0.

CASHBACK / REBATE
  Value = stated cashback amount or (purchase × cashback %)

INSURANCE BONUS / CASHBACK (health, car, home, life, pet, contents, landlord)
  Value = stated gift card / cashback / eGift / EDR dollars / reward dollars amount
  e.g. "$300 EDR Dollars" → 300, "$200 eGift Card" → 200, "$150 cashback" → 150
  For "N weeks free" or "N months free": value = 0 (cannot calculate without knowing premium)
  For "X% cashback on premium": value = 0 (premium amount unknown)

INSURANCE DISCOUNT
  Value = (normal premium − discounted premium) × stated period

BROKERAGE / TRADING BONUS
  Value = stated bonus cash or free trades × $10/trade (ASX standard)

STACKING
  Add any explicitly stackable bonuses.

RULES:
  - Use only stated figures. Do not invent amounts.
  - If no clear dollar value can be extracted, return 0.
  - Maximum value: $2,000 (cap any higher result at 0 — you've made an error)

Reply EXACTLY: VALUE|EXPLANATION
- VALUE: integer AUD, no $ or commas
- EXPLANATION: one sentence, max 20 words, showing the calculation

Examples:
200|$200 cash bonus for depositing $2,000/month for 3 months
945|70,000 Qantas pts × $0.0135 = $945 sign-up bonus
595|Annual fee $595 waived first year
0|Rate comparison only, no stated saving amount"""

    try:
        _haiku_limiter.acquire()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        response = msg.content[0].text.strip()
        parts     = response.split("|", 1)
        raw_val   = parts[0][:30]
        digit_str = "".join(c for c in raw_val if c.isdigit())
        savings   = int(digit_str) if digit_str else 0
        if savings > 2000:
            savings = 0
        explanation = parts[1].strip() if len(parts) > 1 else ""
        return {"savings": savings, "explanation": explanation}
    except Exception as e:
        log.warning(f"Financial value calc failed for '{deal['title']}': {e}")
        return {"savings": 0, "explanation": ""}


def score_financial_deals(deals: list[dict]) -> list[dict]:
    """
    Financial deals: regex parse value first, then Haiku score.
    Falls back to Claude value calc for financial deals where regex finds nothing
    (bank bonuses, credit card points are often described in prose, not price patterns).
    """
    if not deals:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Set email builder defaults
    for deal in deals:
        deal.setdefault("score", 0)
        deal.setdefault("score_reason", "")
        deal.setdefault("cashback_platform", "")
        deal.setdefault("cashback_pct", 0.0)
        deal.setdefault("cashback_url", "")
        deal.setdefault("top_comments", [])
        deal.setdefault("categories", [])
        deal.setdefault("merchant_name", "")
        deal.setdefault("relevance_tags", [])
        deal.setdefault("is_flash", False)
        deal.setdefault("is_expired", False)

    # Step 0: drop health insurance deals — they're not banking/CC/travel
    before = len(deals)
    deals = [
        d for d in deals
        if not any(kw in d.get("title", "").lower() for kw in HEALTH_INSURANCE_SIGNALS)
    ]
    if len(deals) < before:
        log.info(f"  Dropped {before - len(deals)} health insurance deal(s) from financial section")

    # Step 1: regex parse (catches explicit $X bonus, points, % cashback in title)
    log.info("── Financial deals: regex value parsing ──")
    parse_deal_values(deals)

    # Step 2: for deals where regex found nothing, use Claude financial prompt
    # Skip pure rate-announcement deals (HISA) — they never have extractable savings
    RATE_ONLY_SIGNALS = ["% p.a.", "p.a. interest", "interest on balance", "interest rate"]
    no_value = [
        d for d in deals
        if d["savings"] == 0
        and not any(sig in d.get("title", "").lower() for sig in RATE_ONLY_SIGNALS)
    ]
    rate_only_skipped = [d for d in deals if d["savings"] == 0 and d not in no_value]
    if rate_only_skipped:
        log.info(f"  Skipping Claude for {len(rate_only_skipped)} rate-only HISA deal(s) (savings always $0)")
    if no_value:
        log.info(f"── Financial deals: Claude value fallback — {len(no_value)} deals (parallel) ──")
        from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

        def _calc_val(deal):
            return deal, calculate_financial_value(client, deal)

        with ThreadPoolExecutor(max_workers=6) as ex:
            for f in _as_completed({ex.submit(_calc_val, d): d for d in no_value}):
                try:
                    deal, result = f.result()
                    deal["savings"]     = result["savings"]
                    deal["explanation"] = result["explanation"]
                    log.info(f"  ${deal['savings']:>5,} — {deal['title'][:60]}")
                except Exception as e:
                    log.warning(f"Financial value calc error: {e}")

    # Step 3: Haiku score — parallel
    scoreable = [d for d in deals if d.get("savings", 0) >= FIN_MIN_SAVINGS]
    skipped_score = len(deals) - len(scoreable)
    if skipped_score:
        log.info(f"  Skipping scoring for {skipped_score} deal(s) with savings<${FIN_MIN_SAVINGS}")
    log.info(f"── Financial: Haiku scoring {len(scoreable)} deals (parallel) ──")

    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    def _score_fin(deal):
        return deal, assign_score(client, deal)

    with ThreadPoolExecutor(max_workers=6) as ex:
        for f in _as_completed({ex.submit(_score_fin, d): d for d in scoreable}):
            try:
                deal, result = f.result()
                deal["score"]          = result["score"]
                deal["trust_pct"]      = result.get("trust_pct", result["score"] * 10)
                deal["trust_barriers"] = result.get("trust_barriers", [])
                deal["score_reason"]   = result["score_reason"]
                log.info(f"  [{deal['score']}/10] {deal['title'][:60]}")
            except Exception as e:
                log.warning(f"Financial scoring error: {e}")

    # Tag each deal with its sub-type
    for d in deals:
        d["deal_subtype"] = classify_deal(d)

    passed = [
        d for d in deals
        if d["score"] >= FIN_MIN_SCORE and d.get("savings", 0) >= FIN_MIN_SAVINGS
    ]
    log.info(
        f"Financial: {len(passed)}/{len(deals)} deals passed "
        f"score≥{FIN_MIN_SCORE} + savings≥${FIN_MIN_SAVINGS}"
    )
    return passed


# ── Travel deals ──────────────────────────────────────────────────────────────

TRAVEL_MIN_VOTES    = 15
TRAVEL_MIN_COMMENTS = 5
TRAVEL_MIN_CLICKS   = 50


def calculate_travel_value(client: anthropic.Anthropic, deal: dict) -> dict:
    """Value calculator tuned for travel deals."""
    prompt = f"""You are an expert Australian travel deal analyser.

Deal title: {deal['title']}
Votes: {deal['votes']} | Comments: {deal['comments']} | Clicks: {deal['clicks']}

Calculate the TOTAL REALISTIC DOLLAR VALUE / SAVINGS this deal offers.

FLIGHT DEAL
  Savings = (typical retail price for that route/class) − (deal price)
  Use current Qantas/Virgin published fares as benchmark.
  If points redemption: points × $0.0135 per point = value

HOTEL / ACCOMMODATION
  Savings = (rack rate or typical booking price) − (deal price)
  Use known hotel pricing for that property/location.

CRUISE
  Savings = (brochure price) − (deal price), or state the per-person price

CASHBACK / DISCOUNT ON BOOKING PLATFORM
  Value = (purchase amount) × (cashback %)

TRAVEL INSURANCE DISCOUNT
  Value = (normal premium) − (discounted premium)

LOYALTY POINTS BONUS (frequent flyer, hotel points)
  Qantas FF pts: × $0.0135 | Velocity pts: × $0.0135 | Hotel pts: × $0.005

LOUNGE ACCESS
  Value = (day pass price) × (number of passes, default 1)
  Typical AU lounge day pass: $60

RULES:
  - Use only figures stated or clearly inferable from the title.
  - If no savings can be calculated, return 0.
  - Maximum: $5,000 (set to 0 if you'd exceed this — you've made an error).
  - For % discount deals include the effective dollar saving, not just the %.

Reply EXACTLY: VALUE|EXPLANATION
- VALUE: integer AUD savings/value, no $ or commas
- EXPLANATION: one sentence ≤ 20 words showing the calculation

Examples:
350|Melbourne-Tokyo return $750 vs typical $1,100 = $350 saving
675|50,000 Velocity pts × $0.0135 = $675 redemption value
120|20% off Qantas domestic classic seats, avg $600 fare = ~$120 saving
30|BIG4 2-yr membership $30 saving vs individual site bookings
0|Cashback percentage only, no base price stated"""

    try:
        _haiku_limiter.acquire()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}],
        )
        response  = msg.content[0].text.strip()
        parts     = response.split("|", 1)
        digit_str = "".join(c for c in parts[0][:30] if c.isdigit())
        savings   = int(digit_str) if digit_str else 0
        if savings > 5000:
            savings = 0
        explanation = parts[1].strip() if len(parts) > 1 else ""
        return {"savings": savings, "explanation": explanation}
    except Exception as e:
        log.warning(f"Travel value calc failed for '{deal['title']}': {e}")
        return {"savings": 0, "explanation": ""}


def fetch_travel_deals() -> list[dict]:
    """Fetch recent deals from OZB travel category feed."""
    from email.utils import parsedate_to_datetime

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    deals  = []

    for page in range(0, 7):  # more pages to cover 14-day window
        url = f"{TRAVEL_FEED_URL}?page={page}"
        log.info(f"Travel feed page {page}: {url}")
        try:
            xml_text = fetch_feed(url)
        except Exception as e:
            log.warning(f"Travel feed page {page} failed: {e}")
            break

        root    = ET.fromstring(xml_text)
        channel = root.find("channel")
        items   = channel.findall("item")
        if not items:
            break

        page_hits = 0
        for item in items:
            def text(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            meta      = item.find(f"{{{OZB_NS}}}meta")
            meta_attr = meta.attrib if meta is not None else {}

            pub_raw = text("pubDate")
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = datetime.now(timezone.utc)

            if pub_dt < cutoff:
                continue

            page_hits += 1
            deals.append({
                "title":        text("title"),
                "link":         text("link"),
                "external_url": meta_attr.get("url", ""),
                "pubDate":      pub_dt,
                "votes":        int(meta_attr.get("votes-pos",    0)),
                "comments":     int(meta_attr.get("comment-count", 0)),
                "clicks":       int(meta_attr.get("click-count",  0)),
                "expiry_label": _parse_expiry(meta_attr),
                "is_travel":    True,
                "deal_subtype": "travel",
            })

        log.info(f"  Travel page {page}: {len(items)} items, {page_hits} in window")
        if page_hits == 0:
            break

    seen, unique = set(), []
    for d in deals:
        if d["link"] not in seen:
            seen.add(d["link"])
            unique.append(d)

    log.info(f"Travel feed: {len(unique)} unique deals (no age limit)")
    return unique


def score_travel_deals(deals: list[dict]) -> list[dict]:
    """Parse value + score travel deals."""
    if not deals:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for deal in deals:
        deal.setdefault("score", 0)
        deal.setdefault("score_reason", "")
        deal.setdefault("cashback_platform", "")
        deal.setdefault("cashback_pct", 0.0)
        deal.setdefault("cashback_url", "")
        deal.setdefault("market_cheaper", False)
        deal.setdefault("top_comments", [])
        deal.setdefault("categories", ["Travel"])
        deal.setdefault("merchant_name", "")
        deal.setdefault("relevance_tags", [])
        deal.setdefault("is_flash", False)
        deal.setdefault("is_expired", False)
        deal.setdefault("deal_price", 0)

    # Step 1: regex parse
    log.info("── Travel deals: regex value parsing ──")
    parse_deal_values(deals)

    # Step 2 + 3: Claude value fallback AND scoring — both parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed as _asc

    no_value = [d for d in deals if d["savings"] == 0]
    if no_value:
        log.info(f"── Travel: Claude value fallback {len(no_value)} deals (parallel) ──")
        def _tv(deal): return deal, calculate_travel_value(client, deal)
        with ThreadPoolExecutor(max_workers=6) as ex:
            for f in _asc({ex.submit(_tv, d): d for d in no_value}):
                try:
                    deal, r = f.result()
                    deal["savings"]     = r["savings"]
                    deal["explanation"] = r["explanation"]
                except Exception as e:
                    log.warning(f"Travel value error: {e}")

    log.info(f"── Travel: Haiku scoring {len(deals)} deals (parallel) ──")
    def _ts(deal): return deal, assign_score(client, deal)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for f in _asc({ex.submit(_ts, d): d for d in deals}):
            try:
                deal, r = f.result()
                deal["score"]          = r["score"]
                deal["trust_pct"]      = r.get("trust_pct", r["score"] * 10)
                deal["trust_barriers"] = r.get("trust_barriers", [])
                deal["score_reason"]   = r["score_reason"]
            except Exception as e:
                log.warning(f"Travel scoring error: {e}")

    passed = [
        d for d in deals
        if d["score"] >= 5 and d.get("savings", 0) >= TRAVEL_MIN_SAVINGS
    ]
    log.info(
        f"Travel: {len(passed)}/{len(deals)} deals passed "
        f"score≥5 + savings≥${TRAVEL_MIN_SAVINGS}"
    )
    return passed


# ── Food & Grocery deals ─────────────────────────────────────────────────────

FOOD_MIN_VOTES    = 20
FOOD_MIN_COMMENTS = 3
FOOD_MIN_CLICKS   = 50
FOOD_MIN_SCORE    = 5
FOOD_MIN_SAVINGS  = 200   # unified $200 minimum across all categories
HOME_MIN_SAVINGS  = 200   # unified $200 minimum across all categories


def fetch_lifestyle_deals(feeds: list[str], label: str) -> list[dict]:
    """Fetch and deduplicate deals from a list of tag/category feeds — parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed as _asc
    import threading
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    seen, deals = set(), []
    _lock = threading.Lock()

    def _fetch_one(url):
        xml = fetch_feed(url)
        return url, _parse_feed_items(xml, cutoff, url.split("/")[-2])

    with ThreadPoolExecutor(max_workers=6) as ex:
        for f in _asc({ex.submit(_fetch_one, u): u for u in feeds}):
            try:
                url, items = f.result()
                added = 0
                with _lock:
                    for d in items:
                        if d["link"] not in seen:
                            seen.add(d["link"])
                            deals.append(d)
                            added += 1
                if added:
                    log.info(f"  {url.split('/')[-2]}: +{added} unique {label} deals")
            except Exception as e:
                log.warning(f"{label} feed failed: {e}")
    log.info(f"{label} feeds total: {len(deals)} unique deals")
    return deals


def _dedup_by_product(deals: list[dict]) -> list[dict]:
    """
    Remove near-duplicate product listings (same product, different prices/sellers).
    Normalises title by stripping price tokens and punctuation, then keeps the
    highest-scoring deal per normalised key.
    """
    import re
    def _normalise(title: str) -> str:
        t = title.lower()
        # Strip price patterns like $99, US$49, ~A$200
        t = re.sub(r"[a-z~]*\$[\d,\.]+", "", t)
        # Strip common noise tokens
        t = re.sub(r"\b(delivered|delivery|shipped|free|with|and|or|the|at|@|via|plus|\+)\b", "", t)
        # Strip punctuation
        t = re.sub(r"[^\w\s]", " ", t)
        # Collapse whitespace
        return re.sub(r"\s+", " ", t).strip()

    seen: dict[str, dict] = {}
    for d in deals:
        key = _normalise(d.get("title", ""))[:60]
        if key not in seen or d.get("score", 0) > seen[key].get("score", 0):
            seen[key] = d
    return list(seen.values())


def score_lifestyle_deals(deals: list[dict], category: str, icon: str) -> list[dict]:
    """
    Score food/home deals with Haiku.
    No savings threshold — filtered by score only (≥ FOOD_MIN_SCORE).
    """
    if not deals:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for deal in deals:
        deal.setdefault("score", 0)
        deal.setdefault("score_reason", "")
        deal.setdefault("savings", 0)
        deal.setdefault("explanation", "")
        deal.setdefault("deal_price", 0)
        deal.setdefault("cashback_platform", "")
        deal.setdefault("cashback_pct", 0.0)
        deal.setdefault("cashback_url", "")
        deal.setdefault("market_cheaper", False)
        deal.setdefault("top_comments", [])
        deal.setdefault("categories", [category])
        deal.setdefault("merchant_name", "")
        deal.setdefault("relevance_tags", [])
        deal.setdefault("is_flash", False)
        deal.setdefault("is_expired", False)
        deal.setdefault("deal_subtype", category.lower().replace(" & ", "_").replace(" ", "_"))

    # Regex parse savings (catches "Was $X, Now $Y", "Save $X", etc.)
    parse_deal_values(deals)

    # Haiku score all deals — parallel
    log.info(f"── {category}: Haiku scoring {len(deals)} deals (parallel) ──")
    from concurrent.futures import ThreadPoolExecutor, as_completed as _asc

    def _sc(deal): return deal, assign_score(client, deal)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for f in _asc({ex.submit(_sc, d): d for d in deals}):
            try:
                deal, r = f.result()
                deal["score"]          = r["score"]
                deal["trust_pct"]      = r.get("trust_pct", r["score"] * 10)
                deal["trust_barriers"] = r.get("trust_barriers", [])
                deal["score_reason"]   = r["score_reason"]
            except Exception as e:
                log.warning(f"{category} scoring error: {e}")

    scored = [d for d in deals if d["score"] >= FOOD_MIN_SCORE]

    # Apply savings minimums to remove trivial discounts
    min_sav = HOME_MIN_SAVINGS if "home" in category.lower() or "appliance" in category.lower() else FOOD_MIN_SAVINGS
    passed = [d for d in scored if d.get("savings", 0) >= min_sav]
    log.info(
        f"{category}: {len(passed)}/{len(deals)} deals passed "
        f"score≥{FOOD_MIN_SCORE} + savings≥${min_sav}"
    )

    # Deduplicate by normalised product title (keep highest score per product)
    passed = _dedup_by_product(passed)
    log.info(f"{category}: {len(passed)} after product deduplication")
    return passed


# ── Pre-send deal review ─────────────────────────────────────────────────────

def review_and_fix_deals(
    deals: list[dict],
    financial_deals: list[dict],
    cc_travel_deals: list[dict],
    food_deals: list[dict] = None,
    home_deals: list[dict] = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """
    Single-pass Claude Sonnet review of all deal data before the email is sent.

    Checks for:
      - savings=$0 on deals with an obvious stated dollar value in the title
      - Wrong section classification (e.g. CC deal in banking, travel in CC)
      - Explanation that doesn't match the title
      - Score that seems wildly off

    Returns corrected (deals, financial_deals, cc_travel_deals).
    Only one review pass — no retry loop.
    """
    food_deals  = food_deals  or []
    home_deals  = home_deals  or []

    if not ANTHROPIC_API_KEY:
        return deals, financial_deals, cc_travel_deals, food_deals, home_deals

    all_deals = (
        [dict(d, _section="product")   for d in deals] +
        [dict(d, _section="financial") for d in financial_deals] +
        [dict(d, _section="cc_travel") for d in cc_travel_deals] +
        [dict(d, _section="food")      for d in food_deals] +
        [dict(d, _section="home")      for d in home_deals]
    )
    if not all_deals:
        return deals, financial_deals, cc_travel_deals, food_deals, home_deals

    # Build compact review payload — one line per deal
    lines = []
    for i, d in enumerate(all_deals):
        lines.append(
            f"{i}|{d['_section']}|savings={d.get('savings',0)}"
            f"|score={d.get('score',0)}|subtype={d.get('deal_subtype','')}"
            f"|{d['title'][:120]}"
        )

    prompt = f"""You are a quality-control reviewer for an Australian deal alert email.
Below is a list of deals about to be emailed. Each line is:
  INDEX|SECTION|savings=N|score=N|subtype=TYPE|TITLE

Review every deal and return ONLY the ones that have a clear data error.
For each error, output a fix on its own line in EXACTLY this format:
  FIX|INDEX|FIELD|NEW_VALUE

Rules:
- savings: fix if title clearly states a dollar amount (cashback, gift card, bonus, points value)
  but savings=0. Compute the correct integer AUD value.
  Points: Qantas/Velocity = pts × 0.0135, other loyalty = pts × 0.006.
  "N weeks free" or "% cashback" with no base amount → leave as 0.
- subtype: fix if clearly wrong section.
  Valid values: credit_card | banking | travel
  e.g. a Westpac credit card in subtype=banking → FIX|N|subtype|credit_card
- score: only fix if obviously 0 for a high-value deal (>$500 savings). Set to 5.
- Do NOT fix deals that look correct.
- Do NOT add commentary — output FIX lines only, or the word NONE if nothing to fix.

Deals:
{chr(10).join(lines)}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        _haiku_limiter.acquire()
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        response = msg.content[0].text.strip()
        log.info(f"── Pre-send review ──\n{response}")

        if response.upper() == "NONE" or not response:
            log.info("Pre-send review: no errors found")
            return deals, financial_deals, cc_travel_deals, food_deals, home_deals

        # Apply fixes
        fixes_applied = 0
        for line in response.splitlines():
            line = line.strip()
            if not line.startswith("FIX|"):
                continue
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            _, idx_str, field, new_val = parts
            try:
                idx = int(idx_str)
                d   = all_deals[idx]
            except (ValueError, IndexError):
                log.warning(f"Pre-send review: bad index in fix: {line}")
                continue

            if field == "savings":
                try:
                    d["savings"] = int(new_val)
                    fixes_applied += 1
                    log.info(f"  Fixed savings → ${new_val} for: {d['title'][:60]}")
                except ValueError:
                    pass
            elif field == "subtype":
                if new_val in ("credit_card", "banking", "travel"):
                    d["deal_subtype"] = new_val
                    fixes_applied += 1
                    log.info(f"  Fixed subtype → {new_val} for: {d['title'][:60]}")
            elif field == "score":
                try:
                    d["score"] = int(new_val)
                    fixes_applied += 1
                    log.info(f"  Fixed score → {new_val} for: {d['title'][:60]}")
                except ValueError:
                    pass

        log.info(f"Pre-send review: {fixes_applied} fix(es) applied")

        # Rebuild all five lists from the (possibly modified) all_deals
        new_product   = [d for d in all_deals if d["_section"] == "product"]
        new_fin       = [d for d in all_deals if d["_section"] == "financial"]
        new_cc_travel = [d for d in all_deals if d["_section"] == "cc_travel"]
        new_food      = [d for d in all_deals if d["_section"] == "food"]
        new_home      = [d for d in all_deals if d["_section"] == "home"]

        # Re-split financial into banking vs cc_travel based on (possibly fixed) subtype
        cc_from_fin   = [d for d in new_fin if d.get("deal_subtype") in ("credit_card", "travel")]
        pure_fin      = [d for d in new_fin if d.get("deal_subtype") == "banking"]
        new_cc_travel = cc_from_fin + new_cc_travel

        return new_product, pure_fin, new_cc_travel, new_food, new_home

    except Exception as e:
        log.warning(f"Pre-send review failed (sending as-is): {e}")
        return deals, financial_deals, cc_travel_deals, food_deals, home_deals


# ── Gmail alert ───────────────────────────────────────────────────────────────

def send_gmail_alert(
    creds: Credentials,
    deals: list[dict],
    financial_deals: list[dict] = None,
    cc_travel_deals: list[dict] = None,
    food_deals: list[dict] = None,
    home_deals: list[dict] = None,
    extra_deals: list[dict] = None,
    life_event_alerts: list[dict] = None,
    money_audit: list[dict] = None,
    travel_arb: list[dict] = None,
    briefing: dict = None,
):
    if not GMAIL_TO:
        log.warning("GMAIL_TO not set — skipping email")
        return

    financial_deals = financial_deals or []
    cc_travel_deals = cc_travel_deals or []
    food_deals      = food_deals      or []
    home_deals         = home_deals         or []
    extra_deals        = extra_deals        or []
    life_event_alerts  = life_event_alerts  or []
    money_audit        = money_audit        or []
    travel_arb         = travel_arb         or []
    briefing           = briefing           or {}
    flash_count        = sum(1 for d in deals if d.get("is_flash"))
    flash_prefix    = "⚡ FLASH + " if flash_count else ""

    notes = []
    if financial_deals: notes.append(f"💳 {len(financial_deals)} financial")
    if cc_travel_deals: notes.append(f"✈️ {len(cc_travel_deals)} CC/travel")
    if food_deals:      notes.append(f"🍎 {len(food_deals)} food")
    if home_deals:      notes.append(f"🏠 {len(home_deals)} home")
    note_str = " · " + " · ".join(notes) if notes else ""

    all_categorised = deals + financial_deals + cc_travel_deals + food_deals + home_deals + extra_deals
    tier1_count   = sum(1 for d in all_categorised if d.get("tier") == "1_action")
    total_deals   = len(all_categorised)
    total_savings = sum(d.get("savings", 0) for d in all_categorised)
    tier1_str      = f" · 🔴 {tier1_count} Act-Now" if tier1_count else ""
    intel_count    = len([a for a in life_event_alerts if a.get("urgency") in ("immediate","soon")]) + \
                     len([o for o in money_audit if o.get("estimated_value", 0) >= 500])
    intel_str      = f" · 🧠 {intel_count} intel" if intel_count else ""
    subject = (
        f"🤖 OZB | {flash_prefix}{total_deals} deals{tier1_str}{intel_str}{note_str} "
        f"· ~${total_savings:,} AUD savings"
    )

    service = build("gmail", "v1", credentials=creds)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"]      = GMAIL_TO
    if GMAIL_CC:
        msg["Cc"] = GMAIL_CC

    # Plain-text fallback
    plain = "\n\n".join(
        f"[{d['score']}/10] ~${d.get('savings',0):,} — {d['title']}\n"
        f"Value: {d.get('explanation','')}\n"
        f"OZB: {d['link']}\n"
        f"Votes:{d['votes']} Comments:{d['comments']} Clicks:{d['clicks']}"
        + (f"\nCashback: {d['cashback_platform']} ~{d['cashback_pct']:.0f}%" if d.get('cashback_platform') else "")
        for d in all_categorised
    )
    msg.attach(MIMEText(plain, "plain"))

    html = build_email_html(
        deals,
        financial_deals=financial_deals,
        cc_travel_deals=cc_travel_deals,
        food_deals=food_deals,
        home_deals=home_deals,
        extra_deals=extra_deals,
        min_score=MIN_SCORE,
        min_savings=MIN_SAVINGS,
        min_votes=MIN_VOTES,
        min_comments=MIN_COMMENTS,
        min_clicks=MIN_CLICKS,
        fin_min_savings=FIN_MIN_SAVINGS,
        travel_min_savings=TRAVEL_MIN_SAVINGS,
        life_event_alerts=life_event_alerts,
        money_audit=money_audit,
        travel_arb=travel_arb,
        briefing=briefing,
    )
    msg.attach(MIMEText(html, "html"))

    all_recipients = [a.strip() for a in (GMAIL_TO or "").split(",") if a.strip()]
    if GMAIL_CC:
        all_recipients += [a.strip() for a in GMAIL_CC.split(",") if a.strip()]

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    log.info(
        f"Gmail alert sent to {', '.join(all_recipients)} "
        f"({len(deals)} product, {len(financial_deals)} financial, {len(cc_travel_deals)} CC/travel, "
        f"{len(food_deals)} food, {len(home_deals)} home)"
    )

# ── Google Sheets logging ─────────────────────────────────────────────────────




# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== OzBargain Monitor v2 starting ===")

    # 1. Fetch RSS
    deals = fetch_all_deals()

    # 2. Threshold filter
    deals = filter_deals(deals)
    if not deals:
        log.info("No deals passed threshold filters — nothing to do.")
        return

    # 3. Keyword blocklist
    deals = keyword_filter(deals)
    if not deals:
        log.info("All deals dropped by keyword filter — nothing to do.")
        return

    # 4. OOS / expired title filter (Cloudflare blocks page scraping, so detect from title)
    deals = oos_filter(deals)
    if not deals:
        log.info("All deals are OOS/expired — nothing to do.")
        return

    # 5. (Deduplication removed — all qualifying deals are sent every run)

    # 6. Set default enrichment fields (OZB blocks all scraping with Cloudflare)
    for d in deals:
        d.setdefault("thumbnail", "")
        d.setdefault("description", "")
        d.setdefault("top_comments", [])
        d.setdefault("is_expired", False)
        d.setdefault("is_oos", False)
        d.setdefault("categories", [])
        d.setdefault("merchant_name", "")

    # 7. Pre-parse deal prices so StaticICE accessory filter has correct deal_price
    #    (score_deals also calls parse_deal_values later, but analyse_all needs it first)
    parse_deal_values(deals)

    # 7b. Price intelligence: cashback, price-beat, Claude market price
    claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    deals = analyse_all(deals, client=claude_client)

    # 7c. Recalculate savings using Claude market price when available
    for d in deals:
        market = d.get("market_price", 0)
        deal_price_guess = d.get("deal_price", 0)
        current_savings  = d.get("savings", 0)

        if market > 0 and deal_price_guess > 0:
            if d.get("market_cheaper"):
                # Deal is more expensive than market — flag it
                log.info(
                    f"  ⚠️  Cheaper in market: ~${market:,} vs deal ${deal_price_guess:,} "
                    f"— {d['title'][:50]}"
                )
            else:
                # Market is higher → recalculate savings using market as true baseline
                market_savings = market - deal_price_guess
                if market_savings > current_savings:
                    d["savings"]     = market_savings
                    d["explanation"] = (
                        f"{d.get('market_note', 'Market')} ${market:,} → "
                        f"deal ${deal_price_guess:,} = ${market_savings:,} saving"
                    )
                    log.info(
                        f"  ✓ Savings upgraded: ${current_savings:,}→${market_savings:,} "
                        f"(market baseline) — {d['title'][:50]}"
                    )

    # 8. Two-pass Claude scoring (RSS-only — OZB page scraping blocked)
    deals = score_deals(deals)

    # 8. Apply score + savings threshold
    top_deals = [
        d for d in deals
        if d["score"] >= MIN_SCORE and d.get("savings", 0) >= MIN_SAVINGS
    ]
    log.info(f"{len(top_deals)} deal(s) scored {MIN_SCORE}+ with savings ≥ ${MIN_SAVINGS}")

    # 9. Flash deal flagging
    for d in top_deals:
        d["is_flash"] = is_flash_deal(d, flash_hours=6.0, flash_min_score=8)

    flash = [d for d in top_deals if d.get("is_flash")]
    if flash:
        log.info(f"⚡ {len(flash)} flash deal(s) detected")

    # 10. Preference matching + relevance tagging
    top_deals = match_all(top_deals)

    # 11. Fetch + score all secondary sections in parallel
    #     Each section is independent — run them all concurrently.
    from concurrent.futures import ThreadPoolExecutor, as_completed as _asc

    def _lifestyle_pipeline(feeds, label, icon):
        raw = fetch_lifestyle_deals(feeds, label)
        raw = [d for d in raw if d["votes"] >= FOOD_MIN_VOTES
               and d["comments"] >= FOOD_MIN_COMMENTS
               and d["clicks"] >= FOOD_MIN_CLICKS]
        raw = oos_filter(raw)
        return score_lifestyle_deals(raw, label, icon)

    def _financial_pipeline():
        deals = fetch_financial_deals()
        deals = filter_financial_deals(deals)
        return score_financial_deals(deals)

    def _travel_pipeline():
        deals = fetch_travel_deals()
        deals = [d for d in deals
                 if d["votes"] >= TRAVEL_MIN_VOTES
                 and d["comments"] >= TRAVEL_MIN_COMMENTS
                 and d["clicks"] >= TRAVEL_MIN_CLICKS]
        return score_travel_deals(deals)

    section_tasks = {
        "financial":   (_financial_pipeline, ),
        "travel":      (_travel_pipeline, ),
        "food":        (_lifestyle_pipeline, FOOD_FEEDS, "Food & Groceries", "🍎"),
        "home":        (_lifestyle_pipeline, HOME_APPLIANCE_FEEDS, "Home & Appliances", "🏠"),
        "computing":   (_lifestyle_pipeline, COMPUTING_FEEDS, "Computing", "💻"),
        "gaming":      (_lifestyle_pipeline, GAMING_FEEDS, "Gaming", "🎮"),
        "mobile":      (_lifestyle_pipeline, MOBILE_FEEDS, "Mobile", "📱"),
        "electrical":  (_lifestyle_pipeline, ELECTRICAL_FEEDS, "Electrical & Electronics", "⚡"),
        "automotive":  (_lifestyle_pipeline, AUTOMOTIVE_FEEDS, "Automotive", "🚗"),
        "health":      (_lifestyle_pipeline, HEALTH_BEAUTY_FEEDS, "Health & Beauty", "💊"),
        "entertainment":(_lifestyle_pipeline, ENTERTAINMENT_FEEDS, "Entertainment", "🎬"),
        "internet":    (_lifestyle_pipeline, INTERNET_FEEDS, "Internet & Telco", "🌐"),
        "toys":        (_lifestyle_pipeline, TOYS_FEEDS, "Toys & Kids", "🧸"),
        "pets":        (_lifestyle_pipeline, PETS_FEEDS, "Pets", "🐾"),
    }

    section_results = {}
    log.info(f"── Fetching + scoring {len(section_tasks)} sections in parallel ──")
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {}
        for name, task in section_tasks.items():
            fn, *args = task
            futures[ex.submit(fn, *args)] = name
        for f in _asc(futures):
            name = futures[f]
            try:
                section_results[name] = f.result()
                log.info(f"  ✓ {name}: {len(section_results[name])} deals")
            except Exception as e:
                log.warning(f"  ✗ {name} pipeline error: {e}")
                section_results[name] = []

    fin_all    = section_results.get("financial", [])
    travel_deals = section_results.get("travel", [])
    food_deals   = section_results.get("food", [])
    home_deals   = section_results.get("home", [])

    # 11b. Split financial → banking vs CC/travel
    cc_travel_from_fin = [d for d in fin_all if d.get("deal_subtype") in ("credit_card", "travel")]
    fin_deals          = [d for d in fin_all if d.get("deal_subtype") == "banking"]
    cc_travel_deals    = cc_travel_from_fin + travel_deals

    extra_deals = (
        section_results.get("computing", []) +
        section_results.get("gaming", []) +
        section_results.get("mobile", []) +
        section_results.get("electrical", []) +
        section_results.get("automotive", []) +
        section_results.get("health", []) +
        section_results.get("entertainment", []) +
        section_results.get("internet", []) +
        section_results.get("toys", []) +
        section_results.get("pets", [])
    )
    log.info(f"Extra categories total: {len(extra_deals)} deals")

    # 12. Send Gmail alert (always send if any list has deals)
    if not top_deals and not fin_deals and not cc_travel_deals and not food_deals and not home_deals and not extra_deals:
        log.info("No qualifying deals in any feed — no email sent.")
        return

    # 12a. Pre-send review: single Claude pass to catch data errors before email goes out
    log.info("── Pre-send quality review ──")
    top_deals, fin_deals, cc_travel_deals, food_deals, home_deals = review_and_fix_deals(
        top_deals, fin_deals, cc_travel_deals, food_deals, home_deals
    )

    # 12b. Personal opportunity scoring
    log.info("── Personal opportunity scoring ──")
    all_sections = [
        (top_deals,          "product"),
        (fin_deals,          "banking"),
        (cc_travel_deals,    "credit_card"),
        (food_deals,         "food"),
        (home_deals,         "home"),
        (extra_deals,        "other"),
    ]
    for deal_list, section_tag in all_sections:
        for d in deal_list:
            d.setdefault("_section", section_tag)
        score_all_personal(deal_list)


    # 12d. Tier-1 intelligence modules
    log.info("── Life Event Engine ──")
    life_event_alerts = get_life_event_alerts(lookahead_days=120)

    log.info("── Negotiation Scripts ──")
    life_event_alerts = add_negotiation_scripts(life_event_alerts)

    log.info("── Money Left on Table Audit ──")
    money_audit = get_money_audit()

    log.info("── Travel Arbitrage Engine ──")
    travel_arb = get_travel_arb()

    log.info("── Morning Briefing ──")
    all_tier1 = [d for d in (top_deals + fin_deals + cc_travel_deals + food_deals + home_deals + extra_deals)
                 if d.get("tier") == "1_action"]
    briefing = build_briefing(all_tier1, life_event_alerts, money_audit)
    log.info(f"Briefing: {briefing['action_count']} actions · ${briefing['total_value']:,} · {briefing['total_minutes']}min")

    creds = get_google_creds()
    send_gmail_alert(
        creds, top_deals,
        financial_deals=fin_deals,
        cc_travel_deals=cc_travel_deals,
        food_deals=food_deals,
        home_deals=home_deals,
        extra_deals=extra_deals,
        life_event_alerts=life_event_alerts,
        money_audit=money_audit,
        travel_arb=travel_arb,
        briefing=briefing,
    )

    # 13. (mark_sent removed — no deduplication)

    log.info("=== Done ===")

    log.info("=== Done ===")


if __name__ == "__main__":
    main()
