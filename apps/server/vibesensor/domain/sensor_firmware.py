"""Sensor firmware versions: does a sensor run the firmware this Pi would flash?

Firmware builds stamp ``<release version>+<commit>`` into the binary and send it
as the HELLO ``firmware_version`` (``tools/firmware/firmware_build_version.py``).
Release builds carry the server release version (``2026.10.4.1+0123456789ab``);
local builds carry ``0.0.0-dev+<commit>``. Firmware from before the stamp sent a
fixed name without a commit (``esp32-atom-0.1``).
"""

from __future__ import annotations

import re
from typing import Literal

__all__ = ["FirmwareStatus", "firmware_status"]

type FirmwareStatus = Literal["current", "outdated", "unknown"]

_RELEASE_BUILD_RE = re.compile(r"(\d+(?:\.\d+)+)\+[0-9a-f]+")


def _release_key(version: str) -> tuple[int, ...] | None:
    match = _RELEASE_BUILD_RE.fullmatch(version)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def firmware_status(reported: str, bundled: str) -> FirmwareStatus:
    """Compare a sensor's reported firmware with the firmware bundled on the Pi.

    ``bundled`` is empty when the Pi has no firmware bundle or the bundle predates
    version stamping; then nothing can be compared.
    """
    reported = reported.strip()
    if not reported or not bundled:
        return "unknown"
    if reported == bundled:
        return "current"
    if "+" not in reported:
        # Firmware from before build stamping is older than any stamped bundle.
        return "outdated"
    reported_key = _release_key(reported)
    bundled_key = _release_key(bundled)
    if reported_key is not None and bundled_key is not None and reported_key < bundled_key:
        return "outdated"
    # A development build, or a release newer than the firmware this Pi has.
    return "unknown"
