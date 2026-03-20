"""Cross-cutting time utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def parse_iso8601(value: object) -> datetime | None:
    """Parse an ISO 8601 string into an aware ``datetime``, or return ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Ensure timezone-aware: assume UTC for naive timestamps
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def format_duration_mm_ss(seconds: float) -> str:
    """Format a duration as ``MM:SS.s`` while clamping invalid inputs to zero."""
    total = max(0.0, round(float(seconds), 1)) if isfinite(seconds) else 0.0
    minutes = int(total // 60)
    remainder = total - (minutes * 60)
    return f"{minutes:02d}:{remainder:04.1f}"
