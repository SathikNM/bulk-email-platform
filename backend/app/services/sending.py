"""Sending helpers (rate counters). Extended by the bulk engine in Phase 8."""
import uuid
from datetime import datetime, timezone

from app.core.redis import get_redis


def _day_key(account_id: uuid.UUID) -> str:
    return f"sent:{account_id}:{datetime.now(timezone.utc):%Y%m%d}"


def sent_today(account_id: uuid.UUID) -> int:
    return int(get_redis().get(_day_key(account_id)) or 0)
