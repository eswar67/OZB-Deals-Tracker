"""
modules/storage.py
SQLite-backed store for deal history.

Responsibilities:
- filter_unsent(deals)  → return only deals not already alerted
- mark_sent(deals)      → record alerted deals
- is_flash_deal(deal)   → True if posted <6h ago (used for priority flag)
- prune_old()           → keep DB tidy (auto-called on init)
"""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "deal_history.db"
RETENTION_DAYS = 30   # keep sent records for 30 days

log = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_deals (
            link        TEXT PRIMARY KEY,
            title       TEXT,
            sent_at     TEXT NOT NULL,
            savings     INTEGER DEFAULT 0,
            score       INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def prune_old():
    """Delete records older than RETENTION_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    with _connect() as conn:
        deleted = conn.execute(
            "DELETE FROM sent_deals WHERE sent_at < ?", (cutoff,)
        ).rowcount
        conn.commit()
    if deleted:
        log.info(f"Storage: pruned {deleted} old records (>{RETENTION_DAYS}d)")


def filter_unsent(deals: list[dict]) -> list[dict]:
    """Return deals not already in sent_deals table."""
    prune_old()
    if not deals:
        return deals

    links = {d["link"] for d in deals}
    with _connect() as conn:
        placeholders = ",".join("?" * len(links))
        already_sent = {
            row[0]
            for row in conn.execute(
                f"SELECT link FROM sent_deals WHERE link IN ({placeholders})",
                list(links),
            )
        }

    unsent = [d for d in deals if d["link"] not in already_sent]
    skipped = len(deals) - len(unsent)
    if skipped:
        log.info(f"Storage: skipped {skipped} already-alerted deal(s)")
    log.info(f"Storage: {len(unsent)} new deal(s) to process")
    return unsent


def mark_sent(deals: list[dict]):
    """Record deals as sent so they're not re-alerted."""
    if not deals:
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (d["link"], d.get("title", ""), now, d.get("savings", 0), d.get("score", 0))
        for d in deals
    ]
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO sent_deals (link, title, sent_at, savings, score) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    log.info(f"Storage: recorded {len(deals)} deal(s) as sent")


def is_flash_deal(deal: dict, flash_hours: float = 6.0, flash_min_score: int = 8) -> bool:
    """True if deal was posted within flash_hours and has score >= flash_min_score."""
    age_hours = (
        datetime.now(timezone.utc) - deal["pubDate"]
    ).total_seconds() / 3600
    score = deal.get("score", 0)
    return age_hours <= flash_hours and score >= flash_min_score
