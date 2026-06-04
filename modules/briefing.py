"""
modules/briefing.py
───────────────────
Morning Briefing Generator.

Priority order for the executive summary:
  1. Today's actual Tier 1 + Tier 2 OZB deals (what was found today)
  2. Urgent life events (insurance renewals, CC fees due soon)
  3. Money audit items are shown in their own section — NOT in the briefing

This ensures the briefing reflects what's actionable TODAY, not evergreen
financial planning items that are always present.
"""

from datetime import datetime

TIME_ESTIMATES = {
    "insurance":       25,
    "credit_card_fee": 10,
    "travel":           5,
    "deal":             3,
}


def _estimate_time(action_type: str) -> int:
    return TIME_ESTIMATES.get(action_type, 5)


def build_briefing(tier1_deals: list[dict]) -> dict:
    """Build the morning briefing from today's actual Tier-1 OZB deals."""
    combined = []
    for d in sorted(tier1_deals, key=lambda x: x.get("opportunity_score", 0), reverse=True)[:5]:
        savings = d.get("savings", 0)
        title   = d.get("title", "")[:65]
        note    = d.get("ev_note") or d.get("explanation", "")[:80]
        expiry  = d.get("expiry_label", "")
        one_liner = note
        if expiry and "Expires" in expiry:
            one_liner = f"{expiry} · {note}" if note else expiry
        combined.append({
            "icon":        "🔴",
            "title":       title,
            "value":       savings,
            "action_type": "deal",
            "one_liner":   one_liner,
        })

    total_value   = sum(a["value"] for a in combined)
    total_minutes = sum(_estimate_time(a["action_type"]) for a in combined)

    return {
        "date":          datetime.now().strftime("%A, %d %b %Y"),
        "actions":       combined,
        "action_count":  len(combined),
        "total_value":   total_value,
        "total_minutes": total_minutes,
    }
