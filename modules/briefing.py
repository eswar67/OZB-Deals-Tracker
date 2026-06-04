"""
modules/briefing.py
───────────────────
Morning Briefing Generator.

Shows the top deals (by savings) at a glance at the top of the email.
"""

from datetime import datetime


def build_briefing(top_deals: list[dict]) -> dict:
    """Build the morning briefing from the top deals (already sorted by savings)."""
    actions = []
    for d in top_deals[:5]:
        savings   = d.get("savings", 0)
        title     = d.get("title", "")[:65]
        note      = d.get("explanation", "")[:80]
        expiry    = d.get("expiry_label", "")
        one_liner = note
        if expiry and "Expires" in expiry:
            one_liner = f"{expiry} · {note}" if note else expiry
        actions.append({
            "icon":      "🛍",
            "title":     title,
            "value":     savings,
            "one_liner": one_liner,
        })

    return {
        "date":         datetime.now().strftime("%A, %d %b %Y"),
        "actions":      actions,
        "action_count": len(actions),
        "total_value":  sum(a["value"] for a in actions),
    }
