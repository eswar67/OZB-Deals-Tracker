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


def build_briefing(
    tier1_deals: list[dict],
    life_event_alerts: list[dict] = None,  # unused, kept for compatibility
    money_audit: list[dict] = None,        # unused, kept for compatibility
) -> dict:
    """
    Build the morning briefing from today's actual deals + urgent life events only.
    Money audit items are excluded — they live in their own email section.
    """
    actions = []

    # 1. Today's Tier 1 deals — these are real OZB deals found this run
    for d in sorted(tier1_deals, key=lambda x: x.get("opportunity_score", 0), reverse=True)[:4]:
        savings = d.get("savings", 0)
        title   = d.get("title", "")[:65]
        note    = d.get("ev_note") or d.get("explanation", "")[:80]
        expiry  = d.get("expiry_label", "")
        one_liner = note
        if expiry and "Expires" in expiry:
            one_liner = f"{expiry} · {note}" if note else expiry
        actions.append({
            "rank_key":    savings,
            "icon":        "🔴",
            "title":       title,
            "value":       savings,
            "action_type": "deal",
            "one_liner":   one_liner,
            "has_script":  False,
            "source":      "deal",
        })

    # 2. Urgent life events (immediate or soon) — real upcoming deadlines
    for a in life_event_alerts:
        if a.get("urgency") in ("immediate", "soon") and a.get("estimated_value", 0) > 0:
            actions.append({
                "rank_key":    a.get("estimated_value", 0),
                "icon":        a.get("urgency_icon", "🟡"),
                "title":       a.get("event_name", ""),
                "value":       a.get("estimated_value", 0),
                "action_type": a.get("alert_type", "insurance"),
                "one_liner":   f"{a['days_until']} days away — {a.get('action','')[:70]}",
                "has_script":  bool(a.get("script")),
                "source":      "life_event",
            })

    # Sort deals first (by savings), then life events (by value)
    deal_actions  = sorted([a for a in actions if a["source"] == "deal"],
                           key=lambda x: x["rank_key"], reverse=True)
    event_actions = sorted([a for a in actions if a["source"] == "life_event"],
                           key=lambda x: x["rank_key"], reverse=True)

    # Interleave: up to 3 deals + up to 2 life events, capped at 5 total
    combined = (deal_actions[:3] + event_actions[:2])[:5]

    total_value   = sum(a["value"] for a in combined)
    total_minutes = sum(_estimate_time(a["action_type"]) for a in combined)

    return {
        "date":          datetime.now().strftime("%A, %d %b %Y"),
        "actions":       combined,
        "action_count":  len(combined),
        "total_value":   total_value,
        "total_minutes": total_minutes,
    }
