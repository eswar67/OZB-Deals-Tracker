"""
modules/life_events.py
─────────────────────
Life Event Engine — proactive alerts for upcoming personal events.

Instead of waiting for deals to appear, this module asks:
  "What events in Eswar's life create financial opportunities right now?"

Returns a list of alert dicts, each with:
  event_name      str
  days_until      int
  urgency         str   "immediate" | "soon" | "upcoming"
  alert_type      str   "insurance" | "credit_card_fee" | "travel" | "churn"
  headline        str   one-line summary
  detail          str   actionable recommendation
  estimated_value int   AUD potential saving/value
  action          str   what to do
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path

log = logging.getLogger(__name__)

PREFS_FILE = Path(__file__).parent.parent / "user-prefs.json"

# Insurance competitors for comparison (kept static — updated periodically)
INSURANCE_BENCHMARKS = {
    "home": [
        {"provider": "Budget Direct", "est_saving_pct": 23, "notes": "Online discount applied"},
        {"provider": "Honey Insurance", "est_saving_pct": 18, "notes": "IoT discount available"},
        {"provider": "Youi",            "est_saving_pct": 12, "notes": "Usage-based pricing"},
        {"provider": "AAMI",            "est_saving_pct": 10, "notes": "Multi-policy discount"},
    ],
    "car": [
        {"provider": "Budget Direct", "est_saving_pct": 20, "notes": "Online discount"},
        {"provider": "Youi",          "est_saving_pct": 15, "notes": "Usage-based"},
        {"provider": "AAMI",          "est_saving_pct": 12, "notes": "Multi-policy discount"},
    ],
    "landlord": [
        {"provider": "Terri Scheer",   "est_saving_pct": 15, "notes": "Specialist landlord insurer"},
        {"provider": "Budget Direct",  "est_saving_pct": 18, "notes": "Online discount"},
    ],
}


def _urgency(days: int) -> str:
    if days <= 14:
        return "immediate"
    if days <= 45:
        return "soon"
    return "upcoming"


def _urgency_icon(urgency: str) -> str:
    return {"immediate": "🔴", "soon": "🟡", "upcoming": "🔵"}.get(urgency, "⚪")


def _insurance_alert(event: dict, days_until: int) -> dict:
    """Generate insurance renewal alert with competitor quotes."""
    event_type = event.get("notes", "").lower()
    category = "home"
    if "car" in event_type or "car" in event.get("name", "").lower():
        category = "car"
    elif "landlord" in event_type or "landlord" in event.get("name", "").lower():
        category = "landlord"

    premium = event.get("current_premium_aud", 0)
    provider = event.get("current_provider", "current insurer")
    competitors = INSURANCE_BENCHMARKS.get(category, INSURANCE_BENCHMARKS["home"])

    best = max(competitors, key=lambda c: c["est_saving_pct"])
    est_saving = int(premium * best["est_saving_pct"] / 100)
    est_new_premium = premium - est_saving

    urgency = _urgency(days_until)
    icon = _urgency_icon(urgency)

    detail_lines = [f"Current: {provider} — ${premium:,}/year"]
    for c in competitors[:2]:
        s = int(premium * c["est_saving_pct"] / 100)
        detail_lines.append(f"Alt: {c['provider']} ~${premium-s:,}/year (save ~${s:,})")

    return {
        "event_name":      event["name"],
        "days_until":      days_until,
        "urgency":         urgency,
        "urgency_icon":    icon,
        "alert_type":      "insurance",
        "headline":        f"{icon} {event['name']} in {days_until} days — potential saving ~${est_saving:,}",
        "detail":          "\n".join(detail_lines),
        "detail_lines":    detail_lines,
        "competitor":      best["provider"],
        "est_new_premium": est_new_premium,
        "estimated_value": est_saving,
        "action":          f"Get quotes from {best['provider']} and 1-2 others before renewal. "
                           f"Call {provider} retention line with best quote — they often match.",
        "current_provider": provider,
        "current_premium":  premium,
    }


def _credit_card_fee_alert(event: dict, days_until: int) -> dict:
    """Alert for upcoming credit card annual fee — decide retain/cancel/negotiate."""
    card = event.get("card", "credit card")
    fee = event.get("annual_fee_aud", 0)
    urgency = _urgency(days_until)
    icon = _urgency_icon(urgency)

    return {
        "event_name":      event["name"],
        "days_until":      days_until,
        "urgency":         urgency,
        "urgency_icon":    icon,
        "alert_type":      "credit_card_fee",
        "headline":        f"{icon} {card} annual fee (${fee:,}) due in {days_until} days",
        "detail":          f"Annual fee: ${fee:,}. Call retention line 30 days before due date — "
                           f"request fee waiver or bonus points offer.",
        "detail_lines":    [
            f"Annual fee: ${fee:,}",
            "Call retention 30 days before due — ask for fee waiver or 20-50k bonus points",
            f"If declined: consider product change to no-fee card or cancel",
        ],
        "estimated_value": int(fee * 0.4),  # ~40% chance of retention offer
        "action":          f"Call {card} issuer retention team. Script: "
                           f"'I'm reviewing my credit cards and considering cancelling due to the "
                           f"${fee:,} fee. Is there a retention offer available?'",
        "current_provider": card,
        "current_premium":  fee,
    }


def _travel_alert(event: dict, days_until: int) -> dict:
    """Alert for upcoming travel — book now if within booking window."""
    urgency = _urgency(days_until)
    icon = _urgency_icon(urgency)
    notes = event.get("notes", "")

    if days_until <= 60:
        action = "Book immediately — reward seats at T-60 days are limited."
    elif days_until <= 120:
        action = "Book within 2-3 weeks — best award availability is 3-6 months out."
    else:
        action = "Watch for LifeMiles / Velocity award releases. Set calendar reminder for 6-month mark."

    return {
        "event_name":      event["name"],
        "days_until":      days_until,
        "urgency":         urgency,
        "urgency_icon":    icon,
        "alert_type":      "travel",
        "headline":        f"{icon} {event['name']} in {days_until} days",
        "detail":          f"{notes}. {action}",
        "detail_lines":    [notes, action],
        "estimated_value": 0,
        "action":          action,
        "current_provider": "",
        "current_premium":  0,
    }


def get_life_event_alerts(lookahead_days: int = 120) -> list[dict]:
    """
    Return all life event alerts for events within the next `lookahead_days` days,
    sorted by urgency (most urgent first).
    """
    try:
        prefs = json.loads(PREFS_FILE.read_text())
    except Exception as e:
        log.warning(f"Could not load user-prefs.json: {e}")
        return []

    events = prefs.get("personal_profile", {}).get("life_events", [])
    if not events:
        log.info("No life events configured in user-prefs.json")
        return []

    today = date.today()
    alerts = []

    for event in events:
        try:
            event_date = date.fromisoformat(event["date"])
        except (KeyError, ValueError):
            continue

        days_until = (event_date - today).days
        if days_until < 0 or days_until > lookahead_days:
            continue

        etype = event.get("type", "other")
        if etype == "insurance":
            alerts.append(_insurance_alert(event, days_until))
        elif etype == "credit_card_fee":
            alerts.append(_credit_card_fee_alert(event, days_until))
        elif etype == "travel":
            alerts.append(_travel_alert(event, days_until))

    # Sort: immediate first, then by days_until
    priority = {"immediate": 0, "soon": 1, "upcoming": 2}
    alerts.sort(key=lambda a: (priority.get(a["urgency"], 3), a["days_until"]))

    total_value = sum(a["estimated_value"] for a in alerts)
    log.info(
        f"Life Event Engine: {len(alerts)} alert(s) in next {lookahead_days} days "
        f"| ~${total_value:,} estimated value"
    )
    return alerts
