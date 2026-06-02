"""
modules/prefs.py
User preference matching.

Loads user-prefs.json and tags each deal with:
  relevance_tags   list[str]   — matching preference labels
  relevance_score  int         — 0-100 (higher = better match)
  pref_min_savings int         — per-category minimum savings override (or global)

Deals that don't match any preference are still passed through — relevance is
additive context, not a hard filter. (You can filter on relevance_score if desired.)
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

PREFS_FILE = Path(__file__).parent.parent / "user-prefs.json"

_DEFAULT_PREFS = {
    "preferred_categories": [
        "Electronics", "Computing", "Home & Garden", "Travel",
        "Gaming", "Phones", "Appliances"
    ],
    "keyword_watchlist": [
        "iPad", "MacBook", "Dyson", "Roomba", "Sony", "Samsung",
        "standing desk", "Nintendo Switch", "AirPods", "Bose"
    ],
    "excluded_brands": [],
    "excluded_merchants": [],
    "min_savings_per_category": {
        "Electronics": 200,
        "Travel": 100,
        "Supermarket": 50,
        "default": 500
    },
    "preferred_cashback_platform": "ShopBack"
}


def _load_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            with open(PREFS_FILE) as f:
                prefs = json.load(f)
            log.info(f"Loaded user prefs from {PREFS_FILE}")
            return prefs
        except Exception as e:
            log.warning(f"Failed to load {PREFS_FILE}: {e} — using defaults")
    return _DEFAULT_PREFS


def match_deal(deal: dict, prefs: dict) -> dict:
    """
    Tag deal with relevance info based on user prefs.
    Modifies deal in-place, returns it.
    """
    title_lower = deal.get("title", "").lower()
    desc_lower  = deal.get("description", "").lower()
    cats        = [c.lower() for c in deal.get("categories", [])]
    combined    = title_lower + " " + desc_lower

    tags = []
    score = 0

    # ── Keyword watchlist (highest signal) ──────────────────────────────────
    watchlist = [kw.lower() for kw in prefs.get("keyword_watchlist", [])]
    matched_keywords = [kw for kw in watchlist if kw in combined]
    if matched_keywords:
        tags.append(f"👀 Watchlist: {', '.join(matched_keywords[:3])}")
        score += 50 * min(len(matched_keywords), 2)

    # ── Preferred categories ─────────────────────────────────────────────────
    pref_cats = [c.lower() for c in prefs.get("preferred_categories", [])]
    matched_cats = []
    for pref_cat in pref_cats:
        if pref_cat in cats or pref_cat in combined:
            matched_cats.append(pref_cat.title())
    if matched_cats:
        tags.append(f"📂 {', '.join(matched_cats[:2])}")
        score += 20 * min(len(matched_cats), 3)

    # ── Excluded brands/merchants ────────────────────────────────────────────
    excluded_brands    = [b.lower() for b in prefs.get("excluded_brands", [])]
    excluded_merchants = [m.lower() for m in prefs.get("excluded_merchants", [])]
    merchant_lower     = deal.get("merchant_name", "").lower()

    for brand in excluded_brands:
        if brand in combined:
            deal["relevance_tags"]  = ["⛔ Excluded brand"]
            deal["relevance_score"] = -100
            return deal

    for merchant in excluded_merchants:
        if merchant in merchant_lower or merchant in combined:
            deal["relevance_tags"]  = ["⛔ Excluded merchant"]
            deal["relevance_score"] = -100
            return deal

    # ── Cashback platform preference ─────────────────────────────────────────
    pref_cb = prefs.get("preferred_cashback_platform", "")
    if pref_cb and deal.get("cashback_platform") == pref_cb:
        tags.append(f"💰 {pref_cb} cashback")
        score += 15

    # ── Flash deal bonus ─────────────────────────────────────────────────────
    if deal.get("is_flash"):
        tags.append("⚡ Flash Deal")
        score += 10

    # ── Per-category min savings override ────────────────────────────────────
    cat_thresholds = prefs.get("min_savings_per_category", {})
    deal_savings   = deal.get("savings", 0)
    pref_min = cat_thresholds.get("default", 500)
    for matched_cat in matched_cats:
        override = cat_thresholds.get(matched_cat, None)
        if override is not None:
            pref_min = min(pref_min, override)   # use lowest threshold for matched cats
    deal["pref_min_savings"] = pref_min

    deal["relevance_tags"]  = tags
    deal["relevance_score"] = min(score, 100)
    return deal


def match_all(deals: list[dict]) -> list[dict]:
    """Apply preference matching to all deals. Returns same list (mutated)."""
    prefs = _load_prefs()
    log.info(f"── Preference matching: {len(deals)} deals ──")
    for deal in deals:
        match_deal(deal, prefs)
        if deal.get("relevance_score", 0) > 0:
            log.info(
                f"  [{deal['relevance_score']:>3}/100] {deal['title'][:50]} "
                f"→ {deal.get('relevance_tags', [])}"
            )
    return deals
