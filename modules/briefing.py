"""
modules/briefing.py
───────────────────
Morning Briefing Generator.

Produces a concise executive summary card for the top of the email:
  - N actions recommended today
  - Total value
  - Estimated time to act
  - Ranked action list (Tier 1 deals + urgent life events + top money audit)
"""

from datetime import datetime

# Rough time estimates per action type (minutes)
TIME_ESTIMATES = {
    "insurance":       25,
    "credit_card_fee": 10,
    "travel":           5,
    "cc_churn":        20,
    "savings_rate":    15,
    "idle_points":      5,
    "deal":             3,
}


def _estimate_time(action_type: str) -> int:
    return TIME_ESTIMATES.get(action_type, 5)


def build_briefing(
    tier1_deals: list[dict],
    life_event_alerts: list[dict],
    money_audit: list[dict],
) -> dict:
    """
    Compile top actions across all intelligence sources.
    Returns a briefing dict with `actions` list and summary stats.
    """
    actions = []

    # Urgent life events first (immediate or soon)
    for a in life_event_alerts:
        if a.get("urgency") in ("immediate", "soon") and a.get("estimated_value", 0) > 0:
            actions.append({
                "rank_key":    a.get("estimated_value", 0),
                "icon":        a.get("urgency_icon", "🔵"),
                "title":       a.get("event_name", ""),
                "value":       a.get("estimated_value", 0),
                "action_type": a.get("alert_type", "insurance"),
                "one_liner":   a.get("headline", ""),
                "has_script":  bool(a.get("script")),
            })

    # Top money audit opportunities
    for o in money_audit[:3]:
        if o.get("estimated_value", 0) >= 300:
            actions.append({
                "rank_key":    o.get("estimated_value", 0),
                "icon":        o.get("urgency_icon", "🟡"),
                "title":       o.get("headline", ""),
                "value":       o.get("estimated_value", 0),
                "action_type": o.get("type", "cc_churn"),
                "one_liner":   o.get("action", "")[:80],
                "has_script":  False,
            })

    # Top Tier-1 deals
    for d in tier1_deals[:3]:
        actions.append({
            "rank_key":    d.get("opportunity_score", 0) * 10,
            "icon":        "🔴",
            "title":       d.get("title", "")[:60],
            "value":       d.get("savings", 0),
            "action_type": "deal",
            "one_liner":   d.get("ev_note", "") or d.get("explanation", "")[:80],
            "has_script":  False,
        })

    # Sort by value descending, deduplicate, take top 5
    actions.sort(key=lambda a: a["rank_key"], reverse=True)
    actions = actions[:5]

    total_value   = sum(a["value"] for a in actions)
    total_minutes = sum(_estimate_time(a["action_type"]) for a in actions)

    return {
        "date":          datetime.now().strftime("%A, %d %b %Y"),
        "actions":       actions,
        "action_count":  len(actions),
        "total_value":   total_value,
        "total_minutes": total_minutes,
    }
