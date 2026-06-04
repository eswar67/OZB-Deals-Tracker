"""
modules/travel_arb.py
─────────────────────
Award flight search — SYD → India routes.

Deep-links to FREE award-availability aggregators (PointsYeah, AwardTool,
seats.aero) pre-filled for each route. These tools search every loyalty
program at once and show live dates + seat counts — for free.

No hardcoded award charts, point costs, or fabricated availability.
"""

import logging
import urllib.parse

log = logging.getLogger(__name__)

ROUTES = [
    {"origin": "SYD", "dest": "HYD", "label": "Sydney → Hyderabad"},
    {"origin": "SYD", "dest": "MAA", "label": "Sydney → Chennai"},
    {"origin": "SYD", "dest": "BLR", "label": "Sydney → Bengaluru"},
]


def _search_links(origin: str, dest: str) -> list[dict]:
    """Free award-search deep-links for a route, across all programs."""
    return [
        {
            "name": "PointsYeah",
            "note": "free login · all programs",
            "url":  f"https://www.pointsyeah.com/search?origin={origin}&destination={dest}",
        },
        {
            "name": "AwardTool",
            "note": "free · multi-program",
            "url":  f"https://www.awardtool.com/?origin={origin}&destination={dest}",
        },
        {
            "name": "seats.aero",
            "note": "free web search",
            "url":  f"https://seats.aero/search?"
                    + urllib.parse.urlencode({"origin": origin, "destination": dest}),
        },
    ]


def get_travel_arb() -> list[dict]:
    """Return routes with free award-search deep-links. No price/point assumptions."""
    results = []
    for r in ROUTES:
        results.append({
            "route": f"{r['origin']}-{r['dest']}",
            "label": r["label"],
            "links": _search_links(r["origin"], r["dest"]),
        })
    log.info(f"Award search: {len(results)} routes (free aggregator deep-links)")
    return results
