"""Cross-cutting time utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from math import isfinite

_MIN_UTC_OFFSET_SECONDS = -(12 * 60 * 60)
_MAX_UTC_OFFSET_SECONDS = 14 * 60 * 60


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


def format_utc_timestamp(value: object) -> str | None:
    """Format a timestamp as ``YYYY-MM-DD HH:MM:SS UTC`` for human-facing UTC display."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    dt = parse_iso8601(raw)
    if dt is None:
        return raw
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def coerce_utc_offset_seconds(value: object) -> int | None:
    """Return a validated UTC offset in seconds, or ``None`` for invalid input."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        offset_seconds = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        offset_seconds = int(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            offset_seconds = int(raw)
        except ValueError:
            return None
    else:
        return None
    if not (_MIN_UTC_OFFSET_SECONDS <= offset_seconds <= _MAX_UTC_OFFSET_SECONDS):
        return None
    return offset_seconds


def current_utc_offset_seconds() -> int | None:
    """Return the current local UTC offset in seconds."""
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        return None
    return coerce_utc_offset_seconds(int(offset.total_seconds()))


def _format_utc_offset_label(offset_seconds: int) -> str:
    if offset_seconds == 0:
        return "UTC"
    sign = "+" if offset_seconds > 0 else "-"
    total_minutes = abs(offset_seconds) // 60
    hours, minutes = divmod(total_minutes, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def format_timestamp_in_recorded_timezone(
    value: object,
    recorded_utc_offset_seconds: object,
) -> str | None:
    """Format a timestamp in the recorded local offset, falling back to UTC when absent."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    dt = parse_iso8601(raw)
    if dt is None:
        return raw
    offset_seconds = coerce_utc_offset_seconds(recorded_utc_offset_seconds)
    if offset_seconds is None:
        return format_utc_timestamp(raw)
    recorded_tz = timezone(timedelta(seconds=offset_seconds))
    localized = dt.astimezone(recorded_tz)
    return localized.strftime("%Y-%m-%d %H:%M:%S") + " " + _format_utc_offset_label(offset_seconds)


def format_duration_mm_ss(seconds: float) -> str:
    """Format a duration as ``MM:SS.s`` while clamping invalid inputs to zero."""
    total = max(0.0, round(float(seconds), 1)) if isfinite(seconds) else 0.0
    minutes = int(total // 60)
    remainder = total - (minutes * 60)
    return f"{minutes:02d}:{remainder:04.1f}"
