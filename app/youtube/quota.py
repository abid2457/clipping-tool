"""YouTube Data API v3 quota tracker and rate-limit guard."""

from __future__ import annotations

import datetime
from typing import Dict, Any

DAILY_QUOTA_LIMIT = 10_000
UPLOAD_COST = 1_600
READ_COST = 1
UPDATE_COST = 50

# In-memory daily counter synchronized with local date
_DAILY_TRACKER: Dict[str, int] = {}


def _get_today_key() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def get_consumed_quota() -> int:
    """Return total estimated API units used today (UTC)."""
    return _DAILY_TRACKER.get(_get_today_key(), 0)


def get_remaining_quota() -> int:
    """Return remaining API units available today."""
    consumed = get_consumed_quota()
    return max(0, DAILY_QUOTA_LIMIT - consumed)


def record_quota_usage(cost: int) -> int:
    """Record consumed quota units."""
    today = _get_today_key()
    current = _DAILY_TRACKER.get(today, 0)
    new_total = current + cost
    _DAILY_TRACKER[today] = new_total
    return new_total


def can_afford_upload() -> bool:
    """Return True if sufficient quota remains for a video upload (1,600 units)."""
    return get_remaining_quota() >= UPLOAD_COST
