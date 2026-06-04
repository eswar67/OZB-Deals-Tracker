"""
modules/storage.py
Flash-deal detection.

(The old SQLite deal-history store — filter_unsent / mark_sent / prune_old —
was removed: deduplication is no longer used, all qualifying deals are sent
every run. Only the pure flash-deal check remains.)
"""

from datetime import datetime, timezone


def is_flash_deal(deal: dict, flash_hours: float = 6.0, flash_min_score: int = 8) -> bool:
    """True if deal was posted within flash_hours and has score >= flash_min_score."""
    pub = deal.get("pubDate")
    if not pub:
        return False
    age_hours = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
    return age_hours <= flash_hours and deal.get("score", 0) >= flash_min_score
