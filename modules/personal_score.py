"""
modules/personal_score.py
─────────────────────────
Personal Decision Engine — transforms generic deal scores into personalised
Opportunity Scores.

Scoring is category-agnostic: any deal from any category can score high.
Relevance is driven purely by keyword matching against the user's interest
profile — NOT by hard-coding which categories matter.

Computes for every deal:
  opportunity_score   int  0-100
  ev_note             str  one-line context note
  tier                str  "1_action" | "2_watch" | "3_ignore"
  tier_label          str
  personal_reasons    list[str]
  stacking_hint       str
  flight_intel        dict
  deal_quality_label  str
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

PREFS_FILE = Path(__file__).parent.parent / "user-prefs.json"


def _load_profile() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text()).get("personal_profile", {})
        except Exception as e:
            log.warning(f"Could not load personal_profile from user-prefs.json: {e}")
    return {}


# ── Known deal benchmarks (historical context) ───────────────────────────────
DEAL_BENCHMARKS = {
    "lifemiles": [
        (100, "Average"), (125, "Good"), (150, "Great"),
        (175, "Exceptional"), (200, "Rare — act immediately"),
    ],
    "velocity": [
        (15, "Average"), (20, "Good"), (25, "Great"), (30, "Exceptional"),
    ],
    "qantas points": [
        (15, "Average"), (20, "Good"), (30, "Great"),
    ],
    "asia miles": [
        (100, "Average"), (125, "Good"), (150, "Great"), (175, "Exceptional"),
    ],
    "qantas wine": [
        (10000, "Below average"), (15000, "Average"), (20000, "Good"), (25000, "Excellent"),
    ],
}

# ── Stacking combinations ─────────────────────────────────────────────────────
STACKING_PATTERNS = [
    {
        "triggers": ["gift card", "woolworths", "coles", "jb hi-fi", "big w", "myer", "david jones"],
        "hint":     "Stack with ShopBack + Everyday Rewards for extra points",
    },
    {
        "triggers": ["lifemiles", "avianca"],
        "hint":     "Transfer Amex MR → LifeMiles 1:1 + bonus. Book SYD–LAX biz ~68k pts",
    },
    {
        "triggers": ["velocity", "virgin australia"],
        "hint":     "Transfer Amex MR → Velocity 2:1. Good for short-haul premium",
    },
    {
        "triggers": ["qantas", "qff"],
        "hint":     "Earn via Qantas Shopping + Everyday Rewards double-dip",
    },
    {
        "triggers": ["apple", "apple gift card"],
        "hint":     "Stack: Apple GC discount + Westpac Altitude earn + ShopBack cashback",
    },
    {
        "triggers": ["hotel", "hilton", "marriott", "ihg", "hyatt"],
        "hint":     "Book via credit card portal for status + points earn + possible upgrade",
    },
]


def _relevance_score(deal: dict, profile: dict) -> tuple[float, list[str]]:
    """
    Category-agnostic relevance scoring.
    Boosts deals matching high-interest keywords (from user-prefs.json).
    No category is hard-penalised — every deal starts equal.
    Returns (multiplier 0.8–2.0, reasons).
    """
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    reasons  = []
    score    = 1.0

    high_kws = [k.lower() for k in profile.get("high_interest_keywords", [])]
    matched  = [k for k in high_kws if k in combined]

    if matched:
        # Each matched keyword adds 0.2, capped at +1.0 total boost
        boost = min(1.0, 0.2 * len(matched))
        score += boost
        reasons.append(f"Matches interests: {', '.join(matched[:3])}")

    # Also check keyword watchlist
    watchlist = [k.lower() for k in profile.get("keyword_watchlist", [])]
    matched_watch = [k for k in watchlist if k in combined]
    if matched_watch:
        score += 0.3
        reasons.append(f"Watchlist: {', '.join(matched_watch[:2])}")

    return (min(2.0, max(0.8, score)), reasons)


def _probability_of_use(deal: dict, profile: dict) -> tuple[float, str]:
    """
    Estimates realistic probability Eswar would act on this deal.
    Returns (prob 0.3–1.0, note).
    Anchored to spending habits where relevant, otherwise defaults to 0.7.
    """
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    savings  = deal.get("savings", 0)

    # Grocery/supermarket — check against actual spend
    if any(k in combined for k in ["woolworths", "coles", "aldi", "supermarket", "grocery"]):
        monthly_grocery = profile.get("monthly_grocery_spend_aud", 400)
        if savings > monthly_grocery * 2:
            return (0.4, f"High min-spend vs ~${monthly_grocery:,}/month grocery budget")
        return (0.8, f"Aligns with ~${monthly_grocery:,}/month grocery spend")

    # Credit card sign-up bonuses
    if "credit card" in combined or deal.get("deal_subtype") == "credit_card":
        existing = len(profile.get("credit_cards", []))
        if savings >= 800:
            return (0.7, f"Strong bonus — worth adding despite {existing} existing cards")
        if savings >= 400:
            return (0.5, f"Moderate bonus; already hold {existing} cards")
        return (0.3, f"Low bonus; already hold {existing} cards")

    # Points / travel — high probability given profile
    if any(k in combined for k in ["flight", "hotel", "points", "miles", "lounge", "cruise"]):
        return (0.8, "Travel/points — strong match with your profile")

    # Insurance
    if any(k in combined for k in ["insurance"]):
        return (0.6, "Insurance — useful but check renewal timing")

    # Gift cards — flexible, high utility
    if "gift card" in combined:
        return (0.8, "Gift cards — flexible, always useful")

    # Deals with free gifts or high savings — always worth looking at
    if savings >= 500:
        return (0.75, f"High-value deal — ~${savings:,} savings")
    if savings >= 200:
        return (0.7, "Qualified deal — $200+ savings")
    return (0.6, "Deal — check if relevant")


def _urgency_score(deal: dict) -> tuple[float, str]:
    """Returns (urgency multiplier 0.7–1.5, note)."""
    age_mins = deal.get("age_mins", 9999)
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()

    if age_mins < 120:
        return (1.5, "Posted <2h ago")
    if deal.get("is_flash"):
        return (1.4, "Flash deal")
    if any(k in combined for k in ["today only", "24 hours", "ends tonight", "flash"]):
        return (1.3, "Limited time")
    if age_mins < 480:
        return (1.2, "Fresh today")
    if age_mins < 1440:
        return (1.0, "Posted this cycle")
    return (0.7, "Older deal")


def _detect_stacking(deal: dict) -> str:
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    for p in STACKING_PATTERNS:
        if any(t in combined for t in p["triggers"]):
            return p["hint"]
    return ""


def _benchmark_label(deal: dict) -> str:
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    for keyword, thresholds in DEAL_BENCHMARKS.items():
        if keyword in combined:
            nums = re.findall(r'(\d+)(?:%|\s*bonus|\s*points|\s*pts|k\s*points)', combined)
            if nums:
                val   = int(nums[0])
                label = thresholds[0][1]
                for threshold, lbl in thresholds:
                    if val >= threshold:
                        label = lbl
                return f"{label} for {keyword.title()} deal"
    return ""


def _flight_intelligence(deal: dict, profile: dict) -> dict:
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    if not any(k in combined for k in ["flight", "syd", "mel", "bne", "lax", "dxb", "sin", "nrt"]):
        return {}
    savings = deal.get("savings", 0)
    if savings < 200:
        return {}

    cpp_targets = profile.get("travel_cpp_targets", {})
    ecosystems  = profile.get("points_ecosystems", {})

    route_hints = []
    for a, b in [("syd","lax"),("syd","lhr"),("syd","dxb"),("syd","sin"),("mel","lax"),("bne","lax")]:
        if a in combined and b in combined:
            route_hints.append(f"{a.upper()}–{b.upper()}")

    best_path = ""
    if "lifemiles" in combined or savings > 1500:
        pts = ecosystems.get("lifemiles", 0)
        target = cpp_targets.get("lifemiles", 1.4)
        if pts >= 60000:
            best_path = f"LifeMiles ({pts:,} pts) — SYD–LAX biz ~68k pts + ~$120 taxes"
    if not best_path and "qantas" in combined:
        pts = ecosystems.get("qantas", 0)
        best_path = f"Qantas FF ({pts:,} pts) — check classic reward availability"

    verdict = ("Book immediately" if savings >= 3000
               else "Compare points vs cash" if savings >= 1500
               else "Good deal — worth considering")

    return {
        "route":     ", ".join(route_hints) if route_hints else "Route detected",
        "best_path": best_path,
        "verdict":   verdict,
        "cash_saving": savings,
    }


def score_personal(deal: dict, profile: dict) -> dict:
    """
    Opportunity Score = savings_factor × relevance × prob_use × urgency × generic_score.
    No category is penalised. Any deal with strong savings + high generic score
    can reach Tier 1.
    """
    savings       = max(0, deal.get("savings", 0))
    generic_score = deal.get("score", 5)

    # Savings factor: 0→0, $200=0.1, $1000=0.5, $2000+=1.0
    savings_factor = min(1.0, savings / 2000) if savings > 0 else 0.0

    relevance,  rel_reasons = _relevance_score(deal, profile)
    prob_use,   prob_note   = _probability_of_use(deal, profile)
    urgency,    urgency_note = _urgency_score(deal)

    raw = savings_factor * relevance * prob_use * urgency * generic_score * 5
    opportunity_score = max(0, min(100, int(raw)))

    # Boost: any deal with $500+ savings and generic_score ≥ 7 is at least Tier 2
    if savings >= 500 and generic_score >= 7:
        opportunity_score = max(opportunity_score, 30)
    # Boost: $1000+ savings always at least Tier 2
    if savings >= 1000:
        opportunity_score = max(opportunity_score, 35)

    # Boost for premium personal-interest signals
    premium_signals = [
        "lifemiles", "transfer bonus", "business class", "first class",
        "175%", "150%", "200%", "krisflyer", "asia miles",
        "home insurance", "landlord insurance",
    ]
    combined_lower = (deal.get("title","") + " " + deal.get("description","")).lower()
    if any(s in combined_lower for s in premium_signals) and savings >= 400:
        opportunity_score = max(opportunity_score, 60)

    # Tier assignment — purely score-based, no category gates
    if opportunity_score >= 60:
        tier, tier_label = "1_action", "🔴 Tier 1 — Act Now"
    elif opportunity_score >= 30:
        tier, tier_label = "2_watch",  "🟡 Tier 2 — Watch"
    else:
        tier, tier_label = "3_ignore", "⚪ Tier 3"

    personal_reasons = rel_reasons[:2]
    if prob_note:
        personal_reasons.append(prob_note)

    deal["opportunity_score"]  = opportunity_score
    deal["ev_note"]            = prob_note
    deal["tier"]               = tier
    deal["tier_label"]         = tier_label
    deal["personal_reasons"]   = personal_reasons
    deal["stacking_hint"]      = _detect_stacking(deal)
    deal["flight_intel"]       = _flight_intelligence(deal, profile)
    deal["deal_quality_label"] = _benchmark_label(deal)
    deal["urgency_note"]       = urgency_note

    return deal


def score_all_personal(deals: list[dict]) -> list[dict]:
    """Apply personal scoring to every deal. Sorts by opportunity_score desc."""
    profile = _load_profile()
    if not profile:
        log.warning("No personal_profile in user-prefs.json — using generic scoring")

    for deal in deals:
        score_personal(deal, profile)

    deals.sort(key=lambda d: d.get("opportunity_score", 0), reverse=True)

    tier1 = sum(1 for d in deals if d.get("tier") == "1_action")
    tier2 = sum(1 for d in deals if d.get("tier") == "2_watch")
    tier3 = sum(1 for d in deals if d.get("tier") == "3_ignore")
    log.info(f"Personal scores: {tier1} Tier-1 | {tier2} Tier-2 | {tier3} Tier-3")
    return deals
