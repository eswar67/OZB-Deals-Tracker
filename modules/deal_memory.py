"""
modules/deal_memory.py

Persistent deal memory and missed-deal audit helpers.

Runtime files live under outputs/ so they stay local and are ignored by git.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "outputs"
MEMORY_FILE = OUTPUT_DIR / "deal_memory.json"
AUDIT_FILE = OUTPUT_DIR / "missed_deal_audit.jsonl"
LATEST_AUDIT_FILE = OUTPUT_DIR / "latest_missed_deal_audit.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _deal_key(deal: dict) -> str:
    node_id = str(deal.get("node_id") or "").strip()
    if node_id:
        return f"node:{node_id}"
    link = str(deal.get("link") or "").strip()
    if link:
        return f"link:{link}"
    return f"title:{deal.get('title', '').strip().lower()}"


def _load_memory() -> dict:
    if not MEMORY_FILE.exists():
        return {"version": 1, "deals": {}}
    try:
        return json.loads(MEMORY_FILE.read_text())
    except Exception as exc:
        log.warning("Could not read deal memory %s: %s", MEMORY_FILE, exc)
        return {"version": 1, "deals": {}}


def _save_memory(memory: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(memory, indent=2, sort_keys=True))


def annotate_deals(deals: list[dict]) -> list[dict]:
    """Add prior-memory fields before ranking/emailing."""
    memory = _load_memory().get("deals", {})
    for deal in deals:
        key = _deal_key(deal)
        prior = memory.get(key, {})
        prior_best = int(prior.get("best_savings", 0) or 0)
        current = int(deal.get("savings", 0) or 0)

        history = prior.get("price_history", []) or []
        observed_prices = [
            int(h.get("deal_price", 0) or 0)
            for h in history
            if int(h.get("deal_price", 0) or 0) > 0
        ]
        current_price = int(deal.get("deal_price", 0) or 0)
        if current_price > 0:
            observed_prices.append(current_price)
        lowest_price = min(observed_prices) if observed_prices else 0
        lowest_at = ""
        if lowest_price > 0:
            for h in history:
                if int(h.get("deal_price", 0) or 0) == lowest_price:
                    lowest_at = h.get("at", "")
                    break

        deal["memory_key"] = key
        deal["first_seen_at"] = prior.get("first_seen_at", "")
        deal["times_seen"] = int(prior.get("times_seen", 0) or 0)
        deal["email_count"] = int(prior.get("email_count", 0) or 0)
        deal["last_emailed_at"] = prior.get("last_emailed_at", "")
        deal["previous_best_savings"] = prior_best
        deal["price_history"] = history
        deal["lowest_price_seen"] = lowest_price
        deal["lowest_price_at"] = lowest_at
        deal["is_lowest_price"] = bool(
            current_price > 0 and (lowest_price == 0 or current_price <= lowest_price)
        )
        deal["is_new_deal"] = not bool(prior)
        deal["is_best_seen"] = current > 0 and current > prior_best
        deal["is_delta_deal"] = (
            deal["is_new_deal"]
            or deal["email_count"] == 0
            or deal["is_best_seen"]
        )
        if deal["is_new_deal"]:
            deal["delta_reason"] = "new"
        elif deal["email_count"] == 0:
            deal["delta_reason"] = "first_email"
        elif deal["is_best_seen"]:
            deal["delta_reason"] = "saving_improved"
        else:
            deal["delta_reason"] = ""
    return deals


def _compact_deal(deal: dict, reason: str) -> dict:
    return {
        "reason": reason,
        "node_id": deal.get("node_id", ""),
        "title": deal.get("title", ""),
        "link": deal.get("link", ""),
        "savings": int(deal.get("savings", 0) or 0),
        "deal_price": int(deal.get("deal_price", 0) or 0),
        "merchant": deal.get("merchant_name", ""),
        "categories": deal.get("categories", []),
        "relevance_score": int(deal.get("relevance_score", 0) or 0),
        "relevance_tags": deal.get("relevance_tags", []),
        "explanation": deal.get("explanation", ""),
    }


def _drop_reason(deal: dict, sent_keys: set[str], min_savings: int) -> str:
    key = deal.get("memory_key") or _deal_key(deal)
    if key in sent_keys:
        return "emailed"
    if deal.get("is_oos") or deal.get("is_expired"):
        return "out_of_stock_or_expired"
    savings = int(deal.get("savings", 0) or 0)
    if savings <= 0:
        return "no_quantified_savings"
    if savings < min_savings:
        return "below_savings_threshold"
    if deal.get("relevance_score", 0) < 0:
        return "excluded_by_preferences"
    return "not_selected"


def record_run(all_deals: Iterable[dict], emailed_deals: Iterable[dict], min_savings: int) -> dict:
    """
    Update deal memory and write a dropped/missed audit for this run.

    all_deals should be the post-OOS, post-value-enrichment deal list so the
    audit can explain why a fetched deal was or was not emailed.
    """
    all_deals = list(all_deals)
    emailed_deals = list(emailed_deals)
    sent_keys = {(d.get("memory_key") or _deal_key(d)) for d in emailed_deals}
    run_at = _now_iso()

    memory = _load_memory()
    store = memory.setdefault("deals", {})
    for deal in all_deals:
        key = deal.get("memory_key") or _deal_key(deal)
        current = int(deal.get("savings", 0) or 0)
        item = store.setdefault(key, {
            "first_seen_at": run_at,
            "first_title": deal.get("title", ""),
            "link": deal.get("link", ""),
            "node_id": deal.get("node_id", ""),
            "times_seen": 0,
            "email_count": 0,
            "best_savings": 0,
        })
        item["last_seen_at"] = run_at
        item["last_title"] = deal.get("title", "")
        item["last_savings"] = current
        item["deal_price"] = int(deal.get("deal_price", 0) or 0)
        item["market_price"] = int(deal.get("market_price", 0) or 0)
        item["times_seen"] = int(item.get("times_seen", 0) or 0) + 1
        if current > int(item.get("best_savings", 0) or 0):
            item["best_savings"] = current
            item["best_seen_at"] = run_at

        # Append a price observation so we can show lowest-seen / price history.
        # Keep the log compact (cap to the most recent 60 observations).
        deal_price_now = int(deal.get("deal_price", 0) or 0)
        market_price_now = int(deal.get("market_price", 0) or 0)
        history = item.setdefault("price_history", [])
        last_obs = history[-1] if history else {}
        changed = (
            not history
            or int(last_obs.get("deal_price", -1)) != deal_price_now
            or int(last_obs.get("savings", -1)) != current
        )
        if deal_price_now > 0 or current > 0:
            if changed:
                history.append({
                    "at": run_at,
                    "deal_price": deal_price_now,
                    "market_price": market_price_now,
                    "savings": current,
                })
            else:
                last_obs["at"] = run_at  # refresh timestamp without duplicating
            if len(history) > 60:
                del history[:-60]
        if key in sent_keys:
            item["last_emailed_at"] = run_at
            item["email_count"] = int(item.get("email_count", 0) or 0) + 1

    _save_memory(memory)

    dropped = []
    reason_counts = {}
    for deal in all_deals:
        reason = _drop_reason(deal, sent_keys, min_savings)
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if reason != "emailed":
            dropped.append(_compact_deal(deal, reason))

    audit = {
        "run_at": run_at,
        "min_savings": min_savings,
        "fetched_after_oos": len(all_deals),
        "emailed": len(emailed_deals),
        "dropped": len(dropped),
        "reason_counts": reason_counts,
        "top_dropped": sorted(dropped, key=lambda d: d["savings"], reverse=True)[:50],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with AUDIT_FILE.open("a") as f:
        f.write(json.dumps(audit, sort_keys=True) + "\n")
    LATEST_AUDIT_FILE.write_text(json.dumps(audit, indent=2, sort_keys=True))

    log.info(
        "Missed-deal audit: %s emailed, %s dropped (%s)",
        audit["emailed"],
        audit["dropped"],
        ", ".join(f"{k}={v}" for k, v in sorted(reason_counts.items())),
    )
    return audit
