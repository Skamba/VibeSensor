"""Identify the current boot, the span over which ``time.monotonic`` is one clock."""

from __future__ import annotations

from pathlib import Path

__all__ = ["current_boot_id"]

_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def current_boot_id() -> str | None:
    """Return the kernel's random id for this boot, or ``None`` off Linux.

    ``CLOCK_MONOTONIC`` is system-wide and restarts at each boot, so two
    monotonic readings compare only when they carry the same boot id.
    """
    try:
        boot_id = _BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return boot_id or None
