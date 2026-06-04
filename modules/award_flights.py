"""
modules/award_flights.py
────────────────────────
Live award-flight availability via the seats.aero Partner API.

Returns REAL availability — actual dates, cabin, miles cost, remaining seats,
operating airline — for SYD → India routes. No static/made-up data.

Requires env var SEATS_AERO_API_KEY (a seats.aero Pro Partner API key).
If the key is missing, returns [] and the email falls back to booking links.

API docs: https://seats.aero/partnerapi
"""

import os
import logging
from datetime import date, timedelta

import requests

log = logging.getLogger(__name__)

API_BASE = "https://seats.aero/partnerapi"

# Routes to track (origin → destination, IATA)
ROUTES = [
    {"origin": "SYD", "dest": "HYD", "label": "Sydney → Hyderabad"},
    {"origin": "SYD", "dest": "MAA", "label": "Sydney → Chennai"},
    {"origin": "SYD", "dest": "BLR", "label": "Sydney → Bengaluru"},
]

# How far ahead to search (days). Override with SEATS_AERO_DAYS.
SEARCH_DAYS = int(os.getenv("SEATS_AERO_DAYS", "180"))

# Max availability rows to show per route (keeps email readable)
MAX_ROWS_PER_ROUTE = int(os.getenv("SEATS_AERO_MAX_ROWS", "8"))

# Cabin code → label
CABINS = {"Y": "Economy", "W": "Premium Economy", "J": "Business", "F": "First"}

# Friendly names for seats.aero source/program identifiers
SOURCE_LABELS = {
    "singapore":  "KrisFlyer (Singapore Airlines)",
    "krisflyer":  "KrisFlyer (Singapore Airlines)",
    "lifemiles":  "LifeMiles (Avianca)",
    "velocity":   "Velocity (Virgin Australia)",
    "qantas":     "Qantas Frequent Flyer",
    "cathay":     "Asia Miles (Cathay)",
    "asiamiles":  "Asia Miles (Cathay)",
    "eurobonus":  "SAS EuroBonus",
    "emirates":   "Emirates Skywards",
    "etihad":     "Etihad Guest",
    "aeroplan":   "Aeroplan (Air Canada)",
}

# Only surface programs the user can realistically use from Australia
RELEVANT_SOURCES = {
    "singapore", "krisflyer", "lifemiles", "velocity",
    "qantas", "cathay", "asiamiles", "emirates", "etihad",
}


def _label_source(src: str) -> str:
    return SOURCE_LABELS.get(src.lower(), src.title())


def _search_route(api_key: str, origin: str, dest: str) -> list[dict]:
    """Call seats.aero /search for one route, return parsed availability rows."""
    start = date.today()
    end   = start + timedelta(days=SEARCH_DAYS)
    params = {
        "origin_airport":      origin,
        "destination_airport": dest,
        "start_date":          start.isoformat(),
        "end_date":            end.isoformat(),
        "take":                1000,
        "order_by":            "lowest_mileage",
    }
    headers = {"Partner-Authorization": api_key, "Accept": "application/json"}

    try:
        r = requests.get(f"{API_BASE}/search", params=params, headers=headers, timeout=20)
        if r.status_code == 401:
            log.warning("seats.aero: 401 Unauthorized — check SEATS_AERO_API_KEY")
            return []
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        log.warning(f"seats.aero search failed for {origin}-{dest}: {e}")
        return []

    rows = []
    for item in data:
        src = (item.get("Source") or "").lower()
        if src and src not in RELEVANT_SOURCES:
            continue
        dt = item.get("Date", "")
        # Extract each available cabin
        for code, cabin_label in CABINS.items():
            if not item.get(f"{code}Available"):
                continue
            miles_raw = item.get(f"{code}MileageCost", "")
            try:
                miles = int(str(miles_raw).replace(",", "")) if miles_raw else 0
            except ValueError:
                miles = 0
            seats   = item.get(f"{code}RemainingSeats", 0) or 0
            direct  = bool(item.get(f"{code}Direct"))
            airline = item.get(f"{code}Airlines", "") or item.get("Airlines", "")
            rows.append({
                "date":      dt,
                "cabin":     cabin_label,
                "cabin_code":code,
                "program":   _label_source(src),
                "miles":     miles,
                "seats":     seats,
                "direct":    direct,
                "airline":   airline.strip(", "),
            })
    return rows


def get_award_availability() -> list[dict]:
    """
    Return live award availability per route, or [] if no API key.

    Each route dict: {label, origin, dest, rows:[...]}.
    rows are filtered to Economy + Business, sorted by date then miles,
    capped at MAX_ROWS_PER_ROUTE.
    """
    api_key = os.getenv("SEATS_AERO_API_KEY", "").strip()
    if not api_key:
        log.info("SEATS_AERO_API_KEY not set — skipping live award search (using links)")
        return []

    results = []
    for route in ROUTES:
        rows = _search_route(api_key, route["origin"], route["dest"])
        # Keep Economy + Business only (most relevant), dedupe, sort
        rows = [r for r in rows if r["cabin_code"] in ("Y", "J")]
        # Prefer direct + earliest date + fewest miles
        rows.sort(key=lambda r: (r["date"], 0 if r["direct"] else 1, r["miles"]))
        # Dedupe by (date, cabin, program)
        seen, deduped = set(), []
        for r in rows:
            key = (r["date"], r["cabin"], r["program"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        results.append({
            "label":  route["label"],
            "origin": route["origin"],
            "dest":   route["dest"],
            "rows":   deduped[:MAX_ROWS_PER_ROUTE],
            "total":  len(deduped),
        })
        log.info(f"seats.aero {route['origin']}-{route['dest']}: {len(deduped)} availability rows")

    return results
