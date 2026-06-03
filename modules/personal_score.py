"""
modules/personal_score.py
─────────────────────────
Personal Decision Engine — transforms generic deal scores into personalised
Opportunity Scores for Eswar.

Computes for every deal:
  opportunity_score   int  0-100  — Savings × Relevance × Prob_Use × Urgency
  expected_value      int  AUD    — realistic $ value after accounting for spending habits
  ev_note             str         — one-line explanation of expected value calc
  tier                str         — "1_action" | "2_watch" | "3_ignore"
  tier_label          str         — human-readable tier label
  personal_reasons    list[str]   — why this scored high/low personally
  stacking_hint       str         — detected stacking opportunity, or ""
  flight_intel        dict        — populated for flight deals (cpp, points path, verdict)
  deal_quality_label  str         — "Exceptional / Great / Good / Average" vs history
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


# ── Known deal benchmarks (Feature 3 — historical context) ──────────────────
# Format: keyword → list of (threshold, label) sorted ascending
DEAL_BENCHMARKS = {
    "lifemiles": [
        (100, "Average"),
        (125, "Good"),
        (150, "Great"),
        (175, "Exceptional"),
        (200, "Rare — act immediately"),
    ],
    "velocity": [
        (15,  "Average"),
        (20,  "Good"),
        (25,  "Great"),
        (30,  "Exceptional"),
    ],
    "qantas points": [
        (15,  "Average"),
        (20,  "Good"),
        (30,  "Great"),
    ],
    "asia miles": [
        (100, "Average"),
        (125, "Good"),
        (150, "Great"),
        (175, "Exceptional"),
    ],
    "qantas wine": [
        (10000, "Below average"),
        (15000, "Average"),
        (20000, "Good"),
        (25000, "Excellent"),
    ],
}

# ── Stacking combinations to detect ─────────────────────────────────────────
STACKING_PATTERNS = [
    {
        "triggers":    ["gift card", "woolworths", "coles", "jb hi-fi", "big w", "myer", "david jones"],
        "platforms":   ["shopback", "cashrewards", "qantas shopping", "everyday rewards"],
        "hint":        "Stack with ShopBack + Everyday Rewards for extra points",
    },
    {
        "triggers":    ["lifemiles", "avianca"],
        "platforms":   [],
        "hint":        "Transfer Amex MR → LifeMiles for 1:1 + bonus. Book SYD–LAX biz for ~68k pts",
    },
    {
        "triggers":    ["velocity", "virgin australia"],
        "platforms":   [],
        "hint":        "Transfer Amex MR → Velocity 2:1. Good for short-haul premium",
    },
    {
        "triggers":    ["qantas", "qff"],
        "platforms":   ["qantas shopping"],
        "hint":        "Earn via Qantas Shopping + Everyday Rewards double-dip",
    },
    {
        "triggers":    ["apple", "apple gift card"],
        "platforms":   ["shopback", "cashrewards"],
        "hint":        "Stack: Apple GC discount + Westpac Altitude earn + ShopBack cashback",
    },
    {
        "triggers":    ["hotel", "hilton", "marriott", "ihg", "hyatt"],
        "platforms":   [],
        "hint":        "Book via credit card portal for status + points earn + possible upgrade",
    },
]


def _relevance_multiplier(deal: dict, profile: dict) -> tuple[float, list[str]]:
    """
    Returns (multiplier 0.2–2.0, reasons list).
    High-interest categories → up to 2.0×.
    Low-interest → 0.2×.
    """
    combined = (
        (deal.get("title", "") + " " + deal.get("description", "")).lower()
    )
    reasons = []
    score = 1.0

    high_kws = [k.lower() for k in profile.get("high_interest_keywords", [])]
    low_kws  = [k.lower() for k in profile.get("low_interest_keywords", [])]

    matched_high = [k for k in high_kws if k in combined]
    matched_low  = [k for k in low_kws  if k in combined]

    if matched_high:
        boost = min(1.0, 0.25 * len(matched_high))
        score += boost
        reasons.append(f"High-interest: {', '.join(matched_high[:3])}")

    if matched_low:
        score *= 0.25
        reasons.append(f"Low personal relevance: {matched_low[0]}")

    # Section-level boosts
    section = deal.get("_section", deal.get("deal_subtype", ""))
    if section in ("credit_card", "travel"):
        score = max(score, 1.4)
        if not matched_high:
            reasons.append("CC/Travel section — high baseline interest")

    return (min(2.0, max(0.2, score)), reasons)


def _probability_of_use(deal: dict, profile: dict) -> tuple[float, str]:
    """
    Returns (prob 0.05–1.0, note).
    Estimates whether Eswar would actually use this deal.
    """
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    savings  = deal.get("savings", 0)
    section  = deal.get("_section", deal.get("deal_subtype", ""))

    # Grocery/supermarket — realistic spend check
    if any(k in combined for k in ["woolworths", "coles", "aldi", "supermarket", "grocery"]):
        monthly_grocery = profile.get("monthly_grocery_spend_aud", 400)
        # Many cashback deals require a minimum spend; if savings imply large spend, discount
        if savings > monthly_grocery * 2:
            return (0.3, f"Requires ~${savings*3:,} spend; your monthly grocery budget is ~${monthly_grocery:,}")
        return (0.8, f"Grocery spend matches your ~${monthly_grocery:,}/month budget")

    # Credit card sign-up — already have 3 cards, be selective
    if section == "credit_card" or "credit card" in combined:
        existing_cards = profile.get("credit_cards", [])
        # High-value sign-up bonuses are still worth it
        if savings >= 500:
            return (0.6, f"Strong bonus; you already have {len(existing_cards)} premium cards")
        return (0.3, f"Low bonus; you already have {len(existing_cards)} premium cards")

    # Travel/flights — high probability if matching ecosystems
    if section in ("travel",) or any(k in combined for k in ["flight", "hotel", "cruise"]):
        ecosystems = list(profile.get("points_ecosystems", {}).keys())
        if any(eco in combined for eco in ecosystems):
            return (0.85, "Matches your points ecosystem")
        return (0.6, "Travel — generally high relevance")

    # Points transfer bonuses — very high probability
    if any(k in combined for k in ["transfer bonus", "points bonus", "lifemiles", "asia miles"]):
        return (0.9, "Points transfer — high probability of use")

    # Insurance — if renewal month approaching
    import datetime
    current_month = datetime.datetime.now().month
    renewal_months = profile.get("insurance_renewal_months", [])
    if any(k in combined for k in ["insurance", "home insurance", "car insurance", "landlord"]):
        if current_month in renewal_months or (current_month + 1) % 12 in renewal_months:
            return (0.85, "Insurance renewal period approaching")
        return (0.5, "Insurance — relevant but check renewal date")

    # Gift cards — generally high utility
    if "gift card" in combined:
        return (0.75, "Gift cards — flexible, always useful")

    # Generic products
    return (0.4, "Generic product — lower probability of use")


def _urgency_score(deal: dict) -> tuple[float, str]:
    """Returns (urgency 0.5–1.5, note)."""
    age_mins = deal.get("age_mins", 9999)
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()

    if age_mins < 120:
        return (1.5, "Posted <2 hours ago")
    if age_mins < 480:
        return (1.2, "Posted today — fresh")
    if deal.get("is_flash"):
        return (1.4, "Flash deal — limited time")
    if any(k in combined for k in ["today only", "24 hours", "ends tonight", "flash"]):
        return (1.3, "Limited time")
    if age_mins < 1440:
        return (1.0, "Posted this cycle")
    return (0.8, "Older deal")


def _detect_stacking(deal: dict) -> str:
    """Return a stacking hint if combinable opportunities detected."""
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    for pattern in STACKING_PATTERNS:
        if any(t in combined for t in pattern["triggers"]):
            return pattern["hint"]
    return ""


def _benchmark_label(deal: dict) -> str:
    """Check deal against historical benchmarks and return quality label."""
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    for keyword, thresholds in DEAL_BENCHMARKS.items():
        if keyword in combined:
            # Try to extract a percentage or points number from the title
            nums = re.findall(r'(\d+)(?:%|\s*bonus|\s*points|\s*pts|k\s*points)', combined)
            if nums:
                val = int(nums[0])
                label = thresholds[0][1]  # default = lowest
                for threshold, lbl in thresholds:
                    if val >= threshold:
                        label = lbl
                return f"{label} for {keyword.title()} deal"
    return ""


def _flight_intelligence(deal: dict, profile: dict) -> dict:
    """
    For flight deals, compute cents-per-point and suggest best redemption path.
    Returns {} for non-flight deals.
    """
    combined = (deal.get("title", "") + " " + deal.get("description", "")).lower()
    if not any(k in combined for k in ["flight", "syd", "mel", "bne", "lax", "dxb", "sin", "nrt", "hkg"]):
        return {}

    savings = deal.get("savings", 0)
    if savings < 200:
        return {}

    cpp_targets = profile.get("travel_cpp_targets", {})
    ecosystems  = profile.get("points_ecosystems", {})

    # Detect route
    route_hints = []
    for pair in [("syd", "lax"), ("syd", "lhr"), ("syd", "dxb"), ("syd", "sin"),
                 ("mel", "lax"), ("mel", "lhr"), ("bne", "lax")]:
        if pair[0] in combined and pair[1] in combined:
            route_hints.append(f"{pair[0].upper()}–{pair[1].upper()}")

    # Points redemption guidance
    best_path = ""
    if "lifemiles" in combined or savings > 1500:
        pts = ecosystems.get("lifemiles", 0)
        target = cpp_targets.get("lifemiles", 1.4)
        if pts >= 60000:
            best_path = f"LifeMiles ({pts:,} available) — SYD–LAX biz ~68k pts + ~$120 taxes = ~${int(68000 * target / 100):,} value"

    if not best_path and "qantas" in combined:
        pts = ecosystems.get("qantas", 0)
        target = cpp_targets.get("qantas", 1.8)
        best_path = f"Qantas FF ({pts:,} points) — check classic reward availability"

    verdict = ""
    if savings >= 3000:
        verdict = "Book immediately — exceptional value"
    elif savings >= 1500:
        verdict = "Strong deal — compare points redemption vs cash"
    elif savings >= 500:
        verdict = "Good deal — worth considering"

    return {
        "route":    ", ".join(route_hints) if route_hints else "Route detected",
        "best_path": best_path,
        "verdict":  verdict,
        "cash_saving": savings,
    }


def score_personal(deal: dict, profile: dict) -> dict:
    """
    Compute Opportunity Score = Savings_factor × Relevance × Prob_Use × Urgency.
    Attaches all personal intelligence fields to the deal dict.
    Returns the deal (mutated).
    """
    savings = max(0, deal.get("savings", 0))
    generic_score = deal.get("score", 5)

    # Savings factor: normalise to 0–1 range (cap at $2,000)
    savings_factor = min(1.0, savings / 2000) if savings > 0 else 0.05

    relevance, rel_reasons = _relevance_multiplier(deal, profile)
    prob_use, prob_note     = _probability_of_use(deal, profile)
    urgency, urgency_note   = _urgency_score(deal)

    # Raw opportunity score 0–100
    raw = savings_factor * relevance * prob_use * urgency * generic_score * 5
    opportunity_score = max(0, min(100, int(raw)))

    # Expected value = nominal savings × probability of use
    expected_value = int(savings * prob_use)

    # Hard overrides: high-interest keywords on high-value deals always at least Tier 2
    matched_high = [k for k in [kw.lower() for kw in profile.get("high_interest_keywords", [])]
                    if k in (deal.get("title","") + " " + deal.get("description","")).lower()]
    if matched_high and savings >= 200:
        opportunity_score = max(opportunity_score, 35)
    # Points transfer bonuses and premium travel are Tier 1 if savings >= 400
    premium_signals = ["lifemiles", "transfer bonus", "business class", "first class",
                       "175%", "150%", "200%", "krisflyer", "asia miles", "home insurance",
                       "landlord insurance"]
    combined_lower = (deal.get("title","") + " " + deal.get("description","")).lower()
    if any(s in combined_lower for s in premium_signals) and savings >= 400:
        opportunity_score = max(opportunity_score, 60)

    # Tier assignment
    if opportunity_score >= 60:
        tier, tier_label = "1_action", "🔴 Tier 1 — Act Now"
    elif opportunity_score >= 30:
        tier, tier_label = "2_watch",  "🟡 Tier 2 — Worth Watching"
    else:
        tier, tier_label = "3_ignore", "⚪ Tier 3 — Low Priority"

    # Compile personal reasons
    personal_reasons = rel_reasons[:2]
    if prob_note:
        personal_reasons.append(prob_note)

    deal["opportunity_score"]  = opportunity_score
    deal["expected_value"]     = expected_value
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
    """Apply personal scoring to every deal. Mutates in place, returns same list."""
    profile = _load_profile()
    if not profile:
        log.warning("No personal_profile found in user-prefs.json — personal scores will be generic")

    for deal in deals:
        score_personal(deal, profile)

    # Sort by opportunity_score descending within each section
    deals.sort(key=lambda d: d.get("opportunity_score", 0), reverse=True)

    tier1 = [d for d in deals if d.get("tier") == "1_action"]
    tier2 = [d for d in deals if d.get("tier") == "2_watch"]
    tier3 = [d for d in deals if d.get("tier") == "3_ignore"]

    log.info(
        f"Personal scores: {len(tier1)} Tier-1 (Act Now) | "
        f"{len(tier2)} Tier-2 (Watch) | "
        f"{len(tier3)} Tier-3 (Ignore)"
    )
    return deals


def build_net_worth_summary(all_deals: list[dict]) -> dict:
    """
    Compute the 3-row savings reality check for the email header.
    Returns {potential, likely, relevant}.
    """
    potential = sum(d.get("savings", 0) for d in all_deals)
    likely    = sum(d.get("expected_value", d.get("savings", 0)) for d in all_deals)
    relevant  = sum(
        d.get("expected_value", d.get("savings", 0))
        for d in all_deals
        if d.get("tier") in ("1_action", "2_watch")
    )
    return {
        "potential": potential,
        "likely":    likely,
        "relevant":  relevant,
    }
