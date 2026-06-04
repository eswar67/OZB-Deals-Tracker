"""
modules/travel_arb.py
─────────────────────
Award Flight Redemption links for SYD → India routes.

No hardcoded award charts, point costs, cash fares or taxes — those drift
constantly. This just surfaces the routes and direct booking/search links
for each loyalty program so you check live availability and pricing yourself.
"""

import logging

log = logging.getLogger(__name__)

# Direct award-search booking URLs per program
PROGRAMS = [
    {
        "label": "Singapore Airlines (KrisFlyer)",
        "note":  "Direct via SIN — usually the best routing to India",
        "url":   "https://www.singaporeair.com/en_UK/au/ppsclub-krisflyer/use-miles/book-award-flights/",
    },
    {
        "label": "LifeMiles (Avianca)",
        "note":  "Star Alliance — no fuel surcharges, often lowest taxes",
        "url":   "https://www.lifemiles.com/mult/land/LandingAward.aspx",
    },
    {
        "label": "Asia Miles (Cathay)",
        "note":  "Cathay Pacific via HKG",
        "url":   "https://www.cathaypacific.com/cx/en_AU/flying-with-us/asia-miles/use-miles/flights.html",
    },
    {
        "label": "Qantas Classic Rewards",
        "note":  "Emirates or Singapore Airlines codeshare",
        "url":   "https://www.qantas.com/au/en/book-a-trip/flights/classic-rewards.html",
    },
    {
        "label": "Velocity Rewards",
        "note":  "Singapore Airlines / Emirates partner awards",
        "url":   "https://www.virginaustralia.com/au/en/plan/flight-search/?awardSearch=true",
    },
]

ROUTES = [
    {"route": "SYD-HYD", "label": "Sydney → Hyderabad", "via": "via Singapore or Dubai"},
    {"route": "SYD-MAA", "label": "Sydney → Chennai",   "via": "via Singapore"},
    {"route": "SYD-BLR", "label": "Sydney → Bengaluru", "via": "via Singapore or Dubai"},
]


def get_travel_arb() -> list[dict]:
    """Return route + program booking links. No price/point assumptions."""
    results = []
    for r in ROUTES:
        results.append({
            "route":    r["route"],
            "label":    r["label"],
            "via":      r["via"],
            "programs": PROGRAMS,   # same set of search links for every route
        })
    log.info(f"Travel Arb: {len(results)} routes (booking links only)")
    return results
