"""
modules/travel_arb.py
─────────────────────
Travel Arbitrage Engine.

Tracks SYD → HYD / MAA / BLR redemption options in both Economy and Business.
No assumptions about points balance — just shows costs + direct booking links.

Returns list of route dicts, each with:
  route, label, cabin, cash_aud, program_options (with booking_url), typical_carrier
"""

import logging

log = logging.getLogger(__name__)

# Direct booking URLs for reward flights
BOOKING_URLS = {
    "qantas":    "https://www.qantas.com/au/en/book-a-trip/flights/classic-rewards.html",
    "velocity":  "https://www.virginaustralia.com/au/en/plan/flight-search/?awardSearch=true",
    "lifemiles": "https://www.lifemiles.com/mult/land/LandingAward.aspx",
    "asia_miles":"https://www.cathaypacific.com/cx/en_AU/flying-with-us/asia-miles/use-miles/flights.html",
    "krisflyer": "https://www.singaporeair.com/en_UK/au/ppsclub-krisflyer/use-miles/book-award-flights/",
}

PROGRAM_LABELS = {
    "qantas":    "Qantas Classic Rewards",
    "velocity":  "Velocity Rewards",
    "lifemiles": "LifeMiles (Avianca)",
    "asia_miles":"Asia Miles (Cathay)",
    "krisflyer": "KrisFlyer (Singapore Airlines)",
}

# Carrier notes per program for SYD–India routes
CARRIER_NOTES = {
    "qantas":    "Qantas, Emirates or Singapore Airlines codeshare",
    "velocity":  "Singapore Airlines or Emirates via partner awards",
    "lifemiles": "Singapore Airlines, Air India or Thai — no fuel surcharges",
    "asia_miles":"Cathay Pacific via HKG or Singapore Airlines",
    "krisflyer": "Singapore Airlines direct via SIN — best option for India",
}

# SYD → India routes (one-way per person, indicative award costs)
# Typical routing: SYD–SIN–HYD/MAA/BLR or SYD–DXB–HYD
ROUTES = [
    {
        "route":       "SYD-HYD",
        "label":       "Sydney → Hyderabad",
        "via":         "via Singapore or Dubai",
        "cabins": {
            "economy": {
                "cash_aud":  900,
                "programs": {
                    "krisflyer": {"points": 47500, "taxes_aud": 80,  "notes": "Singapore Airlines — best direct routing via SIN"},
                    "lifemiles": {"points": 40000, "taxes_aud": 50,  "notes": "No fuel surcharges — great value"},
                    "asia_miles":{"points": 45000, "taxes_aud": 90,  "notes": "Cathay Pacific via HKG"},
                    "qantas":    {"points": 46800, "taxes_aud": 120, "notes": "Emirates or SQ codeshare"},
                    "velocity":  {"points": 45000, "taxes_aud": 100, "notes": "Singapore Airlines partner award"},
                },
            },
            "business": {
                "cash_aud":  3800,
                "programs": {
                    "krisflyer": {"points": 108000, "taxes_aud": 120, "notes": "Singapore Airlines Business via SIN"},
                    "lifemiles": {"points":  80000, "taxes_aud":  80, "notes": "No fuel surcharges — exceptional value"},
                    "asia_miles":{"points":  95000, "taxes_aud": 120, "notes": "Cathay Pacific Business via HKG"},
                    "qantas":    {"points": 108000, "taxes_aud": 200, "notes": "Emirates Business or SQ codeshare"},
                    "velocity":  {"points":  96000, "taxes_aud": 150, "notes": "Singapore Airlines Business partner award"},
                },
            },
        },
    },
    {
        "route":       "SYD-MAA",
        "label":       "Sydney → Chennai",
        "via":         "via Singapore",
        "cabins": {
            "economy": {
                "cash_aud":  900,
                "programs": {
                    "krisflyer": {"points": 47500, "taxes_aud": 80,  "notes": "Singapore Airlines via SIN — only major carrier"},
                    "lifemiles": {"points": 40000, "taxes_aud": 50,  "notes": "No fuel surcharges"},
                    "qantas":    {"points": 46800, "taxes_aud": 120, "notes": "Singapore Airlines codeshare"},
                    "velocity":  {"points": 45000, "taxes_aud": 100, "notes": "Partner award via SIN"},
                    "asia_miles":{"points": 45000, "taxes_aud": 90,  "notes": "Cathay Pacific via HKG"},
                },
            },
            "business": {
                "cash_aud":  3800,
                "programs": {
                    "krisflyer": {"points": 108000, "taxes_aud": 120, "notes": "Singapore Airlines Business — best product"},
                    "lifemiles": {"points":  80000, "taxes_aud":  80, "notes": "Best value — no surcharges"},
                    "qantas":    {"points": 108000, "taxes_aud": 200, "notes": "SQ codeshare"},
                    "velocity":  {"points":  96000, "taxes_aud": 150, "notes": "Partner award"},
                    "asia_miles":{"points":  95000, "taxes_aud": 120, "notes": "Cathay Business via HKG"},
                },
            },
        },
    },
    {
        "route":       "SYD-BLR",
        "label":       "Sydney → Bengaluru",
        "via":         "via Singapore or Dubai",
        "cabins": {
            "economy": {
                "cash_aud":  900,
                "programs": {
                    "krisflyer": {"points": 47500, "taxes_aud": 80,  "notes": "Singapore Airlines via SIN"},
                    "lifemiles": {"points": 40000, "taxes_aud": 50,  "notes": "No fuel surcharges"},
                    "asia_miles":{"points": 45000, "taxes_aud": 90,  "notes": "Cathay via HKG"},
                    "qantas":    {"points": 46800, "taxes_aud": 120, "notes": "Emirates or SQ codeshare"},
                    "velocity":  {"points": 45000, "taxes_aud": 100, "notes": "Partner award"},
                },
            },
            "business": {
                "cash_aud":  3800,
                "programs": {
                    "krisflyer": {"points": 108000, "taxes_aud": 120, "notes": "Singapore Airlines Business via SIN"},
                    "lifemiles": {"points":  80000, "taxes_aud":  80, "notes": "Best value — no surcharges"},
                    "asia_miles":{"points":  95000, "taxes_aud": 120, "notes": "Cathay Business via HKG"},
                    "qantas":    {"points": 108000, "taxes_aud": 200, "notes": "Emirates Business or SQ"},
                    "velocity":  {"points":  96000, "taxes_aud": 150, "notes": "Partner award"},
                },
            },
        },
    },
]


def get_travel_arb() -> list[dict]:
    """
    Return travel redemption options for all routes.
    No balance checks — just costs and booking links.
    """
    results = []
    for route_cfg in ROUTES:
        route_data = {
            "route": route_cfg["route"],
            "label": route_cfg["label"],
            "via":   route_cfg.get("via", ""),
            "cabins": {},
        }
        for cabin, cabin_cfg in route_cfg["cabins"].items():
            cash_aud = cabin_cfg["cash_aud"]
            options  = []
            for program, rd in cabin_cfg["programs"].items():
                pts      = rd["points"]
                taxes    = rd["taxes_aud"]
                cpp      = round((cash_aud - taxes) / pts * 100, 2) if pts else 0
                options.append({
                    "program":     program,
                    "label":       PROGRAM_LABELS.get(program, program),
                    "points":      pts,
                    "taxes_aud":   taxes,
                    "cpp":         cpp,
                    "notes":       rd.get("notes", ""),
                    "booking_url": BOOKING_URLS.get(program, ""),
                    "cost_str":    f"{pts:,} pts + ${taxes} taxes",
                })
            # Sort by CPP descending (best value first)
            options.sort(key=lambda o: o["cpp"], reverse=True)
            route_data["cabins"][cabin] = {
                "cash_aud": cash_aud,
                "options":  options,
            }
        results.append(route_data)

    log.info(f"Travel Arb: {len(results)} routes × 2 cabins")
    return results
