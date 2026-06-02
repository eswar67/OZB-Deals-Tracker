"""
modules/enricher.py
Scrape the OzBargain deal page for each deal to extract richer metadata.

NOTE: This module is NOT currently called in the main pipeline.
OzBargain pages are protected by Cloudflare, which reliably blocks scraping
even with curl_cffi TLS fingerprint impersonation. All enrichment fields
(thumbnail, description, top_comments, categories, merchant_name) are
defaulted to empty values in main() instead.

This module is retained for future use if Cloudflare bypass improves,
or if a proxy/scraping service is integrated.

Would extract:
  thumbnail       str   — absolute URL of the deal image (or "")
  description     str   — first 400 chars of the deal body text
  top_comments    list  — up to 3 dicts: {author, text, upvotes}
  is_expired      bool  — True if OZB shows an "Expired" badge
  is_oos          bool  — True if comments/badge indicate "out of stock"
  categories      list  — OZB category/tag labels (e.g. ["Electronics", "Computing"])
  merchant_name   str   — clean merchant/store name extracted from page
"""

import logging
import time
import re

from typing import Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

REQUEST_DELAY = 1.5   # seconds between page fetches
TIMEOUT = 20
IMPERSONATE = "chrome124"   # TLS fingerprint to mimic

# Persistent session — reuse connection + cookies across requests
_SESSION: Optional[curl_requests.Session] = None


def _get_session() -> curl_requests.Session:
    """Return a warmed-up curl_cffi Session with OZB cookies."""
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    session = curl_requests.Session(impersonate=IMPERSONATE)
    session.headers.update({
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-AU,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    })

    # Warm up: hit the homepage to pick up Cloudflare clearance cookies
    try:
        r = session.get("https://www.ozbargain.com.au", timeout=TIMEOUT)
        log.info(
            f"Enricher: session warmed up — status {r.status_code} "
            f"(cookies: {list(session.cookies.keys())})"
        )
    except Exception as e:
        log.warning(f"Enricher: homepage warm-up failed: {e} — continuing anyway")

    _SESSION = session
    return _SESSION


def _fetch_page(url: str) -> Optional[BeautifulSoup]:
    session = _get_session()
    try:
        r = session.get(
            url,
            timeout=TIMEOUT,
            headers={"Referer": "https://www.ozbargain.com.au/deals"},
        )
        if r.status_code == 403:
            log.warning(f"Enricher: 403 Cloudflare block on {url}")
            return None
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        log.warning(f"Enricher: failed to fetch {url}: {e}")
        return None


def _extract_thumbnail(soup: BeautifulSoup) -> str:
    for sel in [
        ".node-ozbdeal .field-name-field-image img",
        ".field-name-field-image img",
        "meta[property='og:image']",
    ]:
        tag = soup.select_one(sel)
        if tag:
            src = tag.get("src") or tag.get("content", "")
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                return src
    return ""


def _extract_description(soup: BeautifulSoup) -> str:
    body = soup.select_one(".content.node-ozbdeal .field-name-body")
    if not body:
        body = soup.select_one(".node-ozbdeal .field-items")
    if body:
        text = body.get_text(separator=" ", strip=True)
        return text[:400].strip()
    return ""


def _extract_categories(soup: BeautifulSoup) -> list:
    cats = []
    for tag in soup.select(".taxonomy-term-reference-0 a, .field-name-field-category a"):
        t = tag.get_text(strip=True)
        if t:
            cats.append(t)
    for tag in soup.select(".breadcrumb a"):
        t = tag.get_text(strip=True)
        if t and t not in ("Home", "Deals", ""):
            cats.append(t)
    return list(dict.fromkeys(cats))[:4]


def _extract_merchant(soup: BeautifulSoup) -> str:
    tag = soup.select_one(".coupon-store a, .field-name-field-coupon-store a")
    if tag:
        return tag.get_text(strip=True)
    meta = soup.find("meta", {"name": "author"})
    if meta and meta.get("content"):
        return meta["content"]
    return ""


def _is_expired(soup: BeautifulSoup) -> bool:
    for el in soup.select(".node-ozbdeal .expired, .label-expired, .deal-meta-badge"):
        if "expired" in el.get_text(strip=True).lower():
            return True
    return False


def _is_out_of_stock(soup: BeautifulSoup, top_comments: list) -> bool:
    oos_keywords = ["out of stock", "oos", "sold out", "no longer available", "expired"]
    for el in soup.select(".node-ozbdeal .oos, .deal-meta-badge"):
        if any(k in el.get_text(strip=True).lower() for k in oos_keywords):
            return True
    for c in top_comments:
        if any(k in c.get("text", "").lower() for k in oos_keywords):
            return True
    return False


def _extract_comments(soup: BeautifulSoup, n: int = 3) -> list:
    comments = []
    for el in soup.select(".comment-wrapper, .comment"):
        text_el = el.select_one(".comment-content, .field-name-comment-body")
        if not text_el:
            continue
        text = text_el.get_text(separator=" ", strip=True)[:200]
        if not text:
            continue

        vote_el = el.select_one(".comment-vote-count, .votes-count, .vote-down-count")
        try:
            upvotes = int(re.search(r"\d+", vote_el.get_text()).group()) if vote_el else 0
        except Exception:
            upvotes = 0

        author_el = el.select_one(".username, .comment-author")
        author = author_el.get_text(strip=True) if author_el else "anonymous"

        comments.append({"author": author, "text": text, "upvotes": upvotes})

    comments.sort(key=lambda c: c["upvotes"], reverse=True)
    return comments[:n]


def _set_empty_enrichment(deal: dict):
    deal.update({
        "thumbnail": "", "description": "", "top_comments": [],
        "is_expired": False, "is_oos": False,
        "categories": [], "merchant_name": "",
    })


def enrich_all(deals: list, skip_expired: bool = True) -> list:
    """Enrich all deals with OZB page data. Drops expired/OOS if skip_expired=True.

    Uses curl_cffi to impersonate Chrome TLS fingerprint, bypassing Cloudflare.
    Falls back to RSS-only mode after 3 consecutive failures.
    """
    log.info(f"── Enriching {len(deals)} deals from OZB pages ──")
    enriched = []
    consecutive_failures = 0
    GIVE_UP_AFTER = 3
    scraping_blocked = False

    for i, deal in enumerate(deals):
        if scraping_blocked:
            _set_empty_enrichment(deal)
            enriched.append(deal)
            continue

        soup = _fetch_page(deal.get("link", ""))

        if soup is None:
            consecutive_failures += 1
            _set_empty_enrichment(deal)
            if consecutive_failures >= GIVE_UP_AFTER:
                scraping_blocked = True
                log.warning(
                    f"Enricher: {GIVE_UP_AFTER} consecutive failures — "
                    f"switching to RSS-only mode for remaining {len(deals) - i - 1} deals."
                )
            enriched.append(deal)
        else:
            consecutive_failures = 0
            top_comments = _extract_comments(soup)
            deal["thumbnail"]     = _extract_thumbnail(soup)
            deal["description"]   = _extract_description(soup)
            deal["top_comments"]  = top_comments
            deal["is_expired"]    = _is_expired(soup)
            deal["is_oos"]        = _is_out_of_stock(soup, top_comments)
            deal["categories"]    = _extract_categories(soup)
            deal["merchant_name"] = _extract_merchant(soup)

            flags = [f for f, v in [("EXPIRED", deal["is_expired"]), ("OOS", deal["is_oos"])] if v]
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            log.info(
                f"Enriched: {deal['title'][:55]}{flag_str} | "
                f"img={'yes' if deal['thumbnail'] else 'no'} | "
                f"cats={deal['categories']}"
            )

            if skip_expired and (deal.get("is_expired") or deal.get("is_oos")):
                log.info(f"  Dropping expired/OOS: {deal['title'][:55]}")
                continue
            enriched.append(deal)

        if i < len(deals) - 1 and not scraping_blocked:
            time.sleep(REQUEST_DELAY)

    dropped = len(deals) - len(enriched)
    if dropped:
        log.info(f"Enricher: dropped {dropped} expired/OOS deal(s)")
    if scraping_blocked:
        log.info("Enricher: running in RSS-only mode (no page thumbnails/comments)")
    log.info(f"Enricher: {len(enriched)} deal(s) passed through")
    return enriched
