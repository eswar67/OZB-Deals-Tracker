"""
modules/expiry_check.py

Verify whether remembered deals are still live on OzBargain.

A deal's title is a weak expiry signal — most posters never edit it when the
deal dies. OzBargain itself is authoritative: an expired node renders
``<span class="nodeexpiry expired">`` and a ``<span class="expired">expired</span>``
status banner. This module fetches node pages and records the verdict in deal
memory so the website can hide dead deals.

Expiry is terminal: once a node is marked expired we never re-check it, so the
per-run cost falls away as the backlog is classified.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) OzBargainDealTracker/1.0"
NODE_URL = "https://www.ozbargain.com.au/node/{node_id}"

# The status banner OzBargain puts at the top of a dead node, and the expiry
# stamp in the node's meta links. Either one alone is enough.
_EXPIRED_BANNER = re.compile(r'<span\s+class="expired"\s*>\s*expired\s*</span>', re.I)
_EXPIRED_STAMP = re.compile(r'class="nodeexpiry\s+expired"[^>]*>(?:<[^>]+>)*\s*([^<]*)', re.I)

MAX_WORKERS = 4
TIMEOUT = 20
# OzBargain starts returning 503 when a burst arrives, so pace each worker and
# back off rather than writing off a live deal as unreachable.
REQUEST_SPACING = 0.35
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3

_throttle = Lock()
_last_request = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pace() -> None:
    """Keep a global minimum gap between outbound requests."""
    global _last_request
    with _throttle:
        wait = REQUEST_SPACING - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _fetch(url: str) -> tuple[int, str]:
    status = 0
    for attempt in range(MAX_ATTEMPTS):
        _pace()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            status = exc.code
            if exc.code not in RETRY_STATUSES:
                return exc.code, ""
        except Exception as exc:  # network flake, DNS, timeout
            log.debug("Expiry check failed for %s: %s", url, exc)
            status = 0
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(1.5 * (attempt + 1))
    return status, ""


def check_node(node_id: str) -> dict | None:
    """Return {'expired': bool, 'expires_on': str} or None when undetermined.

    A 404/410 means the node was pulled entirely — treat that as expired. Any
    other failure returns None so the caller leaves the deal untouched rather
    than hiding a live deal because the network hiccuped.
    """
    status, html = _fetch(NODE_URL.format(node_id=node_id))
    if status in (404, 410):
        return {"expired": True, "expires_on": ""}
    if status != 200 or not html:
        return None

    stamp = _EXPIRED_STAMP.search(html)
    if stamp or _EXPIRED_BANNER.search(html):
        return {"expired": True, "expires_on": (stamp.group(1).strip() if stamp else "")}
    return {"expired": False, "expires_on": ""}


def _needs_check(item: dict) -> bool:
    if item.get("expired"):
        return False  # terminal — a dead deal never comes back
    return bool(item.get("node_id") or re.search(r"/node/(\d+)", str(item.get("link", ""))))


def _node_id(item: dict) -> str:
    node_id = str(item.get("node_id") or "").strip()
    if node_id:
        return node_id
    match = re.search(r"/node/(\d+)", str(item.get("link", "")))
    return match.group(1) if match else ""


def refresh_expiry(store: dict, limit: int = 400) -> dict:
    """Check up to `limit` unclassified deals in `store` and mark the dead ones.

    Least-recently-checked deals go first so the workload spreads evenly across
    runs instead of hammering the same nodes. Mutates `store` in place and
    returns a summary for logging.
    """
    candidates = [(key, item) for key, item in store.items() if _needs_check(item)]
    candidates.sort(key=lambda pair: pair[1].get("expiry_checked_at", ""))
    candidates = candidates[:limit]
    if not candidates:
        return {"checked": 0, "expired": 0, "live": 0, "unknown": 0}

    def work(pair):
        key, item = pair
        return key, check_node(_node_id(item))

    counts = {"checked": len(candidates), "expired": 0, "live": 0, "unknown": 0}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for key, verdict in pool.map(work, candidates):
            if verdict is None:
                counts["unknown"] += 1
                continue
            item = store[key]
            item["expiry_checked_at"] = _now_iso()
            if verdict["expired"]:
                item["expired"] = True
                if verdict["expires_on"]:
                    item["expires_on"] = verdict["expires_on"]
                counts["expired"] += 1
            else:
                item["expired"] = False
                counts["live"] += 1

    log.info(
        "Expiry check: %s node(s) verified — %s expired, %s live, %s unreachable",
        counts["checked"], counts["expired"], counts["live"], counts["unknown"],
    )
    return counts
