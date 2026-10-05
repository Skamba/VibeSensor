"""Sensor firmware identities: does a sensor run the firmware this Pi would flash?

Firmware builds stamp an identity ``fw-<date>+<digest>`` into the binary and send
it as the HELLO ``firmware_version`` (``tools/firmware/firmware_build_version.py``).
The digest covers the firmware build inputs, so equal digests mean the same
firmware; the date (``YYYYMMDD.HHMM``, of the newest commit touching those inputs)
orders different firmware. Server releases do not change it.

Older firmware sent other strings: a server release stamp
(``2026.10.4.36+444e90c6c19d``), a dev stamp (``0.0.0-dev+<commit>``) or a fixed
name (``esp32-atom-0.1``).
"""

from __future__ import annotations

import re
from typing import Literal

__all__ = ["FirmwareStatus", "firmware_status", "is_firmware_identity"]

type FirmwareStatus = Literal["current", "outdated", "unknown"]

_IDENTITY_RE = re.compile(r"fw-(?P<date>\d{8}\.\d{4})\+(?P<digest>[0-9a-f]{12})")


def is_firmware_identity(version: str) -> bool:
    """True when *version* is a build identity, not an older stamp."""
    return _IDENTITY_RE.fullmatch(version) is not None


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
    bundled_id = _IDENTITY_RE.fullmatch(bundled)
    if bundled_id is None:
        # A bundle from before firmware identities: no order to compare with.
        return "unknown"
    reported_id = _IDENTITY_RE.fullmatch(reported)
    if reported_id is None:
        # Firmware from before identities is older than any bundle that has one.
        return "outdated"
    if reported_id["digest"] == bundled_id["digest"]:
        # Same build inputs, committed at another date (a cherry-pick) or built
        # where git could not tell the date.
        return "current"
    if reported_id["date"] < bundled_id["date"]:
        return "outdated"
    # Newer firmware than this Pi has, or a local build with uncommitted changes.
    return "unknown"
