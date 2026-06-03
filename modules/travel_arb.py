"""
modules/travel_arb.py
─────────────────────
Travel Arbitrage Engine.

For each configured route, calculates CPP (cents per point) across all of
Eswar's points programs and recommends the best booking method.

Returns a list of route_analysis dicts, one per route, each with:
  route           str   "SYD-DXB"
  label           str   "Sydney → Dubai"
  cabin           str   "business"
  pax             int
  cash_aud        int   typical cash fare
  program_options list[dict]  — sorted by cpp desc
  best            dict  — best program option
  verdict         str   "Book with X" | "Pay cash" | "Wait for sale"
  summary_line    str   one-liner for email
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

PREFS_FILE = Path(__file__).parent.parent / "user-prefs.json"

# Min CPP to recommend points redemption over cash (per program)
MIN_CPP_RECOMMEND = {
    "qantas":    1.8,
    "velocity":  1.5,
    "lifemiles": 1.4,
    "asia_miles":1.6,
    "amex_mrp":  1.2,
}

PROGRAM_LABELS = {
    "qantas":    "Qantas FF",
    "velocity":  "Velocity",
    "lifemiles": "LifeMiles",
    "asia_miles":"Asia Miles",
    "amex_mrp":  "Amex MRP",
}

# Rough availability notes per program (qualitative)
AVAILABILITY_NOTES = {
    "qantas":    "Classic rewards — hard to find; book 353 days out",
    "velocity":  "Partner awards available; good for Emirates",
    "lifemiles": "No fuel surcharges; Star Alliance; book any time",
    "asia_miles":"Cathay, Qatar, BA; low carrier-imposed surcharges",
    "amex_mrp":  "Transfer to partner first; adds 3-5 day delay",
}


def _analyse_route(route_cfg: dict, ecosystems: dict, cpp_targets: dict) -> dict:
    """Analyse one route across all programs the user has points in."""
    route      = route_cfg["route"]
    label      = route_cfg["label"]
    pax        = route_cfg.get("pax", 1)
    cabin      = route_cfg.get("cabin", "economy")
    cash_total = route_cfg.get("typical_cash_aud", 0) * pax
    programs   = route_cfg.get("programs", {})

    options = []
    for program, redemption in programs.items():
        pts_per_pax  = redemption["points"]
        taxes_per_pax = redemption.get("taxes_aud", 0)
        pts_total    = pts_per_pax * pax
        taxes_total  = taxes_per_pax * pax
        balance      = ecosystems.get(program, 0)

        # CPP = (cash value - taxes) / points used
        net_value = cash_total - taxes_total
        cpp = (net_value / pts_total) if pts_total > 0 else 0

        min_cpp      = cpp_targets.get(program, MIN_CPP_RECOMMEND.get(program, 1.5))
        recommended  = cpp >= min_cpp
        can_afford   = balance >= pts_total
        shortfall    = max(0, pts_total - balance)

        verdict_line = ""
        if not can_afford:
            verdict_line = f"⚠️ Short {shortfall:,} pts (have {balance:,})"
        elif recommended:
            verdict_line = f"✅ Recommended — {cpp:.2f}¢/pt (target {min_cpp:.2f}¢)"
        else:
            verdict_line = f"❌ Below target — {cpp:.2f}¢/pt (target {min_cpp:.2f}¢)"

        options.append({
            "program":       program,
            "label":         PROGRAM_LABELS.get(program, program.title()),
            "pts_per_pax":   pts_per_pax,
            "pts_total":     pts_total,
            "taxes_total":   taxes_total,
            "balance":       balance,
            "can_afford":    can_afford,
            "shortfall":     shortfall,
            "cpp":           round(cpp, 2),
            "min_cpp":       min_cpp,
            "recommended":   recommended,
            "verdict_line":  verdict_line,
            "availability":  AVAILABILITY_NOTES.get(program, ""),
            "total_cost_str": f"{pts_total:,} pts + ${taxes_total:,} taxes",
        })

    # Sort: recommended + can_afford first, then by cpp
    options.sort(key=lambda o: (not (o["recommended"] and o["can_afford"]), -o["cpp"]))

    # Determine overall verdict
    best_affordable = next((o for o in options if o["recommended"] and o["can_afford"]), None)
    best_any        = options[0] if options else None

    if best_affordable:
        verdict = f"✅ Book with {best_affordable['label']} — {best_affordable['cpp']:.2f}¢/pt"
        summary_line = (
            f"{label} {cabin.replace('_',' ').title()} × {pax}pax: "
            f"Best = {best_affordable['label']} "
            f"({best_affordable['pts_total']:,} pts + ${best_affordable['taxes_total']:,}) "
            f"@ {best_affordable['cpp']:.2f}¢/pt — "
            f"saves ~${cash_total - best_affordable['taxes_total']:,} vs cash"
        )
    elif best_any and not best_any["can_afford"]:
        verdict = f"⚠️ Best program ({best_any['label']}) but short {best_any['shortfall']:,} pts"
        summary_line = f"{label}: Need {best_any['shortfall']:,} more {best_any['label']} pts"
    else:
        verdict = f"💵 Pay cash — no program meets CPP target (best: {best_any['cpp']:.2f}¢/pt)" if best_any else "💵 Pay cash"
        summary_line = f"{label}: Pay cash — points redemption below target for all programs"

    return {
        "route":          route,
        "label":          label,
        "cabin":          cabin,
        "pax":            pax,
        "cash_total":     cash_total,
        "program_options": options,
        "best":           best_affordable or best_any,
        "verdict":        verdict,
        "summary_line":   summary_line,
    }


def get_travel_arb() -> list[dict]:
    """
    Analyse all configured routes and return results sorted by:
    1. Recommended + affordable routes first
    2. Then by cash saving potential
    """
    try:
        prefs = json.loads(PREFS_FILE.read_text())
    except Exception as e:
        log.warning(f"Could not load user-prefs.json: {e}")
        return []

    profile    = prefs.get("personal_profile", {})
    routes     = profile.get("travel_routes", [])
    ecosystems = profile.get("points_ecosystems", {})
    cpp_targets = profile.get("travel_cpp_targets", {})

    if not routes:
        return []

    results = [_analyse_route(r, ecosystems, cpp_targets) for r in routes]

    # Sort: bookable recommendations first, then by cash saving
    results.sort(key=lambda r: (
        not (r["best"] and r["best"]["recommended"] and r["best"]["can_afford"]),
        -(r["cash_total"] - (r["best"]["taxes_total"] if r["best"] else 0))
    ))

    bookable = [r for r in results if r["best"] and r["best"]["recommended"] and r["best"]["can_afford"]]
    log.info(
        f"Travel Arb: {len(results)} route(s) analysed | "
        f"{len(bookable)} with recommended & affordable redemption"
    )
    return results
