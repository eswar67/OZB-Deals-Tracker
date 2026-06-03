"""
modules/money_audit.py
──────────────────────
Money Left on the Table Detector.

Every run asks: "What financial opportunities is Eswar missing right now?"

Checks:
  1. Credit card churn eligibility (held > min months → new bonus available)
  2. Savings account rate gap (current rate vs best available)
  3. Points sitting idle (large balances expiring or devaluing)

Returns a list of opportunity dicts, sorted by estimated_value descending.
Each dict has:
  type            str   "cc_churn" | "savings_rate" | "idle_points"
  headline        str
  detail_lines    list[str]
  estimated_value int   AUD
  action          str
  urgency         str   "immediate" | "soon" | "upcoming"
  urgency_icon    str
"""

import json
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

PREFS_FILE = Path(__file__).parent.parent / "user-prefs.json"

# Points value per program (AUD per point)
POINTS_CPP = {
    "qantas":    0.0135,
    "velocity":  0.0135,
    "lifemiles": 0.012,
    "asia_miles":0.014,
    "amex_mrp":  0.007,  # transferable — value depends on transfer partner
}

# Threshold: balance worth alerting on (AUD value)
IDLE_POINTS_THRESHOLD_AUD = 500


def _urgency(days: int) -> str:
    if days <= 14:  return "immediate"
    if days <= 45:  return "soon"
    return "upcoming"

def _urgency_icon(u: str) -> str:
    return {"immediate": "🔴", "soon": "🟡", "upcoming": "🔵"}.get(u, "⚪")


def _check_cc_churn(profile: dict) -> list[dict]:
    """Find credit cards eligible for churning to capture new sign-up bonuses."""
    held_cards   = profile.get("credit_card_portfolio", [])
    churn_targets = profile.get("cc_churn_targets", [])
    today = date.today()
    opps = []

    # Map currently held cards to months held
    held_map = {}
    for card in held_cards:
        try:
            held_since = date.fromisoformat(card["held_since"])
            months_held = (today.year - held_since.year) * 12 + (today.month - held_since.month)
            held_map[card["card"].lower()] = {
                "months": months_held,
                "card": card,
            }
        except (KeyError, ValueError):
            continue

    # Check each currently held card: has it been held long enough to replace?
    for held in held_cards:
        card_name = held["card"]
        try:
            held_since = date.fromisoformat(held["held_since"])
            months_held = (today.year - held_since.year) * 12 + (today.month - held_since.month)
        except (KeyError, ValueError):
            continue

        # Eligible to churn after 12+ months (standard rule)
        if months_held >= 12:
            # Find best available churn target for this card's program
            program = held.get("points_program", "qantas")
            candidates = [t for t in churn_targets if t.get("points_program") == program]
            if not candidates:
                candidates = churn_targets  # fall back to any

            for target in sorted(candidates, key=lambda t: t.get("bonus_points", 0), reverse=True)[:1]:
                bonus_pts   = target.get("bonus_points", 0)
                cpp         = POINTS_CPP.get(target.get("points_program", "qantas"), 0.013)
                bonus_value = int(bonus_pts * cpp)
                annual_fee  = target.get("annual_fee_aud", 0)
                net_value   = bonus_value - annual_fee
                min_spend   = target.get("min_spend_aud", 0)
                min_months  = target.get("min_spend_months", 3)

                if net_value <= 0:
                    continue

                opps.append({
                    "type":          "cc_churn",
                    "urgency":       "soon",
                    "urgency_icon":  "🟡",
                    "headline":      f"🟡 Credit card churn: {target['card']} — {bonus_pts:,} pts (~${bonus_value:,} value)",
                    "detail_lines":  [
                        f"Currently holding: {card_name} ({months_held} months) ✅ eligible",
                        f"Target: {target['card']} — {bonus_pts:,} bonus {target.get('points_program','').title()} pts",
                        f"Bonus value: ~${bonus_value:,} | Annual fee: ${annual_fee:,} | Net: ~${net_value:,}",
                        f"Min spend: ${min_spend:,} over {min_months} months (~${min_spend//min_months:,}/month)",
                        target.get("notes", ""),
                    ],
                    "estimated_value": net_value,
                    "action":          f"Apply for {target['card']}. Spend ${min_spend:,} over {min_months} months "
                                       f"to earn {bonus_pts:,} bonus pts. Consider cancelling {card_name} at "
                                       f"renewal to avoid double fees.",
                })

    return opps


def _check_savings_rate(profile: dict) -> list[dict]:
    """Find savings accounts earning below current best rates."""
    accounts   = profile.get("savings_accounts", [])
    benchmarks = profile.get("savings_benchmarks", [])
    opps = []

    if not benchmarks:
        return []

    # Best available rate from benchmarks (excluding offset — that's special)
    non_offset = [a for a in accounts if "offset" not in a.get("bank", "").lower()]
    best_benchmark = max(benchmarks, key=lambda b: b["rate_pct"])

    for account in non_offset:
        current_rate = account.get("current_rate_pct", 0)
        balance      = account.get("balance_aud", 0)
        bank         = account.get("bank", "current account")

        gap = best_benchmark["rate_pct"] - current_rate
        if gap <= 0.1:
            continue  # not worth switching for <0.1% difference

        annual_gain = int(balance * gap / 100)
        if annual_gain < 100:
            continue

        opps.append({
            "type":          "savings_rate",
            "urgency":       "soon" if annual_gain >= 500 else "upcoming",
            "urgency_icon":  "🟡" if annual_gain >= 500 else "🔵",
            "headline":      f"💸 Savings rate gap: ${annual_gain:,}/year left on table",
            "detail_lines":  [
                f"Current: {bank} @ {current_rate}% on ${balance:,}",
                f"Best available: {best_benchmark['bank']} @ {best_benchmark['rate_pct']}%",
                f"Conditions: {best_benchmark['conditions']}",
                f"Annual gain: ~${annual_gain:,}",
            ],
            "estimated_value": annual_gain,
            "action":          f"Open {best_benchmark['bank']} and transfer funds. "
                               f"Conditions: {best_benchmark['conditions']}.",
        })

    return opps


def _check_idle_points(profile: dict) -> list[dict]:
    """Flag large points balances sitting idle without a redemption plan."""
    ecosystems = profile.get("points_ecosystems", {})
    opps = []

    for program, balance in ecosystems.items():
        cpp   = POINTS_CPP.get(program, 0.01)
        value = int(balance * cpp)
        if value < IDLE_POINTS_THRESHOLD_AUD:
            continue

        # Check if there are travel routes configured that use this program
        travel_routes = profile.get("travel_routes", [])
        routes_using = [
            r for r in travel_routes
            if program in r.get("programs", {})
        ]

        if routes_using:
            best_route = min(routes_using, key=lambda r: r["programs"][program]["points"])
            pts_needed = best_route["programs"][program]["points"]
            taxes      = best_route["programs"][program]["taxes_aud"]
            cash_equiv = best_route.get("typical_cash_aud", 0)
            cpp_actual = (cash_equiv - taxes) / pts_needed if pts_needed else 0
            target_cpp = profile.get("travel_cpp_targets", {}).get(program, 1.5)

            if balance >= pts_needed:
                note = (
                    f"✅ Enough for {best_route['label']} {best_route['cabin'].replace('_',' ')} "
                    f"({pts_needed:,} pts + ${taxes} taxes)"
                )
            else:
                shortfall = pts_needed - balance
                note = f"⚠️ Short {shortfall:,} pts for {best_route['label']}"

            opps.append({
                "type":          "idle_points",
                "urgency":       "upcoming",
                "urgency_icon":  "🔵",
                "headline":      f"🔵 {program.title()} balance: {balance:,} pts (~${value:,}) — have a redemption plan?",
                "detail_lines":  [
                    f"Balance: {balance:,} pts | Est. value: ~${value:,} AUD",
                    note,
                    f"CPP at this route: {cpp_actual:.2f}¢ | Your target: {target_cpp:.2f}¢",
                ],
                "estimated_value": value,
                "action":          f"Plan {program.title()} redemption for {best_route['label']}. "
                                   f"Check award availability at redemption-ready destinations.",
            })

    return opps


def get_money_audit(lookahead_days: int = 90) -> list[dict]:
    """
    Run the full money audit. Returns list of opportunities sorted by value.
    """
    try:
        prefs = json.loads(PREFS_FILE.read_text())
    except Exception as e:
        log.warning(f"Could not load user-prefs.json: {e}")
        return []

    profile = prefs.get("personal_profile", {})

    opps  = []
    opps += _check_cc_churn(profile)
    opps += _check_savings_rate(profile)
    opps += _check_idle_points(profile)

    opps.sort(key=lambda o: o.get("estimated_value", 0), reverse=True)

    total = sum(o.get("estimated_value", 0) for o in opps)
    log.info(
        f"Money Audit: {len(opps)} opportunity/ies found | "
        f"~${total:,} total left on table"
    )
    return opps
