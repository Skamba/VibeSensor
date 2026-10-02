"""Unit conversion constants shared across runtime and diagnostics."""

from __future__ import annotations

from typing import Final

MPS_TO_KMH: Final[float] = 3.6
"""Multiply metres-per-second by this to get kilometres-per-hour."""

KMH_TO_MPS: Final[float] = 1.0 / MPS_TO_KMH
"""Multiply kilometres-per-hour by this to get metres-per-second."""

SECONDS_PER_MINUTE: Final[float] = 60.0
"""Hz-to-RPM conversion factor (RPM = Hz × 60)."""
