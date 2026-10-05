"""Correct an unsynchronised Pi clock from the browser's clock.

The Pi has no RTC. Without internet, systemd-timesyncd restores the clock from
the last saved time, so runs get stamped days or months in the past. The phone
or laptop showing the UI usually has network time, so the UI reports its clock
on connect and this module steps the system clock when:

* the kernel says the clock is unsynchronised (``adjtimex`` reports
  ``TIME_ERROR``), so an NTP-synced clock is never overridden;
* the clock is off by more than ``CLOCK_STEP_THRESHOLD_S``;
* no run is recording, so one run never spans a clock step;
* it has not stepped it before in this process.

Stepping needs ``CAP_SYS_TIME``, which the systemd unit grants. Without it
(dev machines, containers) the attempt is logged once and skipped. Sensor
timing runs on ``time.monotonic``, which a step does not move.

``clock_trusted`` says whether a run starting now gets a true start time: the
kernel clock is NTP-synchronised, or the last browser report found it within
the threshold (or stepped it). Until a browser reports, an unsynchronised Pi
clock is not trusted.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock

__all__ = [
    "CLOCK_STEP_THRESHOLD_S",
    "BrowserClockCorrector",
    "ClockAction",
    "ClockReportResult",
    "kernel_clock_synchronized",
]

LOGGER = logging.getLogger(__name__)

CLOCK_STEP_THRESHOLD_S = 10.0
"""Smaller offsets are left alone: they do not matter for run timestamps."""

# adjtimex(2) returns TIME_ERROR while the kernel's STA_UNSYNC flag is set.
_TIME_ERROR = 5
# Larger than ``struct timex`` on every ABI; zeroed means modes=0 (read-only).
_TIMEX_BUFFER_BYTES = 512


class ClockAction(StrEnum):
    """What the server did with one browser clock report."""

    STEPPED = "stepped"
    WITHIN_THRESHOLD = "within_threshold"
    NTP_SYNCHRONIZED = "ntp_synchronized"
    SYNC_STATE_UNKNOWN = "sync_state_unknown"
    RECORDING = "recording"
    ALREADY_STEPPED = "already_stepped"
    NOT_PERMITTED = "not_permitted"


@dataclass(frozen=True, slots=True)
class ClockReportResult:
    action: ClockAction
    offset_s: float
    """Browser clock minus server clock when the report arrived."""


_CLOCK_MATCHES_BROWSER = frozenset({ClockAction.STEPPED, ClockAction.WITHIN_THRESHOLD})
# Far off the browser and not stepped. ``ALREADY_STEPPED`` keeps the earlier verdict:
# the step set the clock, so a later far-off report is a browser with a wrong clock.
_CLOCK_LEFT_WRONG = frozenset(
    {ClockAction.RECORDING, ClockAction.NOT_PERMITTED, ClockAction.SYNC_STATE_UNKNOWN}
)


def kernel_clock_synchronized() -> bool | None:
    """Return whether an NTP client has synchronised the kernel clock.

    ``None`` when the state cannot be read (non-Linux, no libc ``adjtimex``).
    A read-only ``adjtimex`` call needs no privileges.
    """
    if sys.platform != "linux":
        return None
    try:
        adjtimex = ctypes.CDLL(None, use_errno=True).adjtimex
    except (OSError, AttributeError):
        return None
    state = adjtimex(ctypes.create_string_buffer(_TIMEX_BUFFER_BYTES))
    if state < 0:
        return None
    return bool(state != _TIME_ERROR)


def _step_realtime_clock(epoch_s: float) -> None:
    time.clock_settime(time.CLOCK_REALTIME, epoch_s)


class BrowserClockCorrector:
    """Apply the stepping policy described in the module docstring."""

    __slots__ = (
        "_lock",
        "_now",
        "_permission_denied",
        "_recording",
        "_step",
        "_stepped",
        "_synchronized",
        "_browser_agrees",
    )

    def __init__(
        self,
        *,
        recording: Callable[[], bool],
        synchronized: Callable[[], bool | None] = kernel_clock_synchronized,
        step: Callable[[float], None] = _step_realtime_clock,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._recording = recording
        self._synchronized = synchronized
        self._step = step
        self._now = now
        self._lock = Lock()
        self._stepped = False
        self._permission_denied = False
        # Whether the clock matched the last browser report (after any step);
        # ``None`` before the first report.
        self._browser_agrees: bool | None = None

    def report(self, browser_epoch_ms: int) -> ClockReportResult:
        """Handle the browser's clock reading taken just before it sent the report."""
        with self._lock:
            browser_s = browser_epoch_ms / 1000.0
            offset_s = browser_s - self._now()
            action = self._decide(offset_s)
            if action is ClockAction.STEPPED:
                action = self._try_step(browser_s, offset_s)
            if action in _CLOCK_MATCHES_BROWSER:
                self._browser_agrees = True
            elif action in _CLOCK_LEFT_WRONG:
                self._browser_agrees = False
            return ClockReportResult(action=action, offset_s=round(offset_s, 3))

    def clock_trusted(self) -> bool:
        """Whether the wall clock is right: NTP-synchronised or confirmed by a browser.

        On a platform whose sync state is unknown it is trusted unless a browser
        found it off and it could not be stepped.
        """
        synchronized = self._synchronized()
        if synchronized:
            return True
        # One attribute read, without the lock: the recorder asks while holding its own.
        browser_agrees = self._browser_agrees
        if browser_agrees is not None:
            return browser_agrees
        return synchronized is None

    def _decide(self, offset_s: float) -> ClockAction:
        if abs(offset_s) <= CLOCK_STEP_THRESHOLD_S:
            return ClockAction.WITHIN_THRESHOLD
        if self._stepped:
            return ClockAction.ALREADY_STEPPED
        if self._permission_denied:
            return ClockAction.NOT_PERMITTED
        synchronized = self._synchronized()
        if synchronized is None:
            return ClockAction.SYNC_STATE_UNKNOWN
        if synchronized:
            return ClockAction.NTP_SYNCHRONIZED
        if self._recording():
            return ClockAction.RECORDING
        return ClockAction.STEPPED

    def _try_step(self, browser_s: float, offset_s: float) -> ClockAction:
        try:
            self._step(browser_s)
        except PermissionError:
            self._permission_denied = True
            LOGGER.info(
                "System clock is unsynchronised and %.0f s off the browser clock, "
                "but this process may not set it (no CAP_SYS_TIME)",
                offset_s,
            )
            return ClockAction.NOT_PERMITTED
        except OSError as exc:
            self._permission_denied = True
            LOGGER.warning("Could not set the system clock: %s", exc)
            return ClockAction.NOT_PERMITTED
        self._stepped = True
        LOGGER.warning(
            "Stepped the unsynchronised system clock by %+.1f s to the browser clock",
            offset_s,
        )
        return ClockAction.STEPPED
