"""Sensor timing guard: a synced sensor's timestamps against server receive time.

Every DATA frame carries ``t0_us``, the time of its first sample on the server
clock once the sensor applied its sync offset. Analysis trusts those stamps and
the declared sample rate: a sensor whose stamps fall behind real time (a
firmware that stamps from a nominal schedule while delivering fewer samples) or
that delivers samples at a different rate than it declares produces data that
cannot be placed on the run's timeline, and a run can end with no usable
samples at all.

The guard compares, per window of receive time:

- the **arrival lag**: receive time minus the time of the frame's last sample.
  The window minimum strips Wi-Fi and retransmit delays; on a healthy sensor it
  stays at the frame build and send latency (tens of ms) and does not grow.
- the **effective rate**: samples delivered per second of receive time
  (frames lost in transit counted from sequence gaps), against the declared
  rate.

Both measures hold only once the sensor's send queue is in its steady state.
The sensor sends stop-and-wait and holds a frame up to 3 s
(``kDataMaxFrameAgeMs``); right after it connects, reconnects or is synced, and
after any interruption, its queue still holds frames that are drained faster
than real time. A window anchored on a queued frame and closed on a fresh one
counts too many samples (0.75 s of backlog is 3.75 % of 20 s), so the guard
starts a window only after the stream has run ``SENSOR_TIMING_SETTLE_S`` without
an interruption.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "SENSOR_TIMING_MAX_LAG_US",
    "SENSOR_TIMING_MAX_RATE_ERROR",
    "SENSOR_TIMING_SETTLE_S",
    "SENSOR_TIMING_WINDOW_S",
    "SensorTimingGuard",
    "SensorTimingState",
]

type SensorTimingState = Literal["unknown", "ok", "timestamp_lag", "rate_mismatch"]

SENSOR_TIMING_WINDOW_S = 20.0
# The sensor holds a frame back at most 3 s (``kDataMaxFrameAgeMs``), plus up to
# four 120 ms retransmits once sent: a link that keeps it that far behind still
# delivers correctly stamped frames. A window whose fastest frame arrives later
# than this is stamped behind real time.
SENSOR_TIMING_MAX_LAG_US = 3_500_000
# Arrival jitter over a 20 s window is well under 1 %; an untrimmed sensor
# oscillator is a few percent off.
SENSOR_TIMING_MAX_RATE_ERROR = 0.02
# A sensor's backlog (at most 3 s of frames) drains within a second once its
# frames are acknowledged promptly; a server still starting acknowledges slowly
# for longer. The registry's stream-start grace for frame loss is as long.
SENSOR_TIMING_SETTLE_S = 5.0
# No frame for this long from a sensor that sends several a second and resends an
# unacknowledged one every 120 ms: the stream was interrupted and its queue
# drains again.
_INTERRUPTION_S = 1.0
# A frame stamped this far ahead of its arrival means a wrong clock offset.
_MAX_LEAD_US = 250_000


@dataclass(slots=True)
class SensorTimingGuard:
    """Per-sensor timing check; ``state`` is the verdict of the last full window."""

    state: SensorTimingState = "unknown"
    min_lag_us: int | None = None
    effective_rate_hz: float | None = None
    _settled_mono_s: float | None = None
    _last_receive_mono_s: float | None = None
    _window_first_mono_s: float | None = None
    _window_samples: int = 0
    _window_min_lag_us: int | None = None

    def reset(self) -> None:
        """Forget the sensor's timing (it restarted or lost its clock sync)."""
        self.state = "unknown"
        self.min_lag_us = None
        self.effective_rate_hz = None
        self._settled_mono_s = None
        self._last_receive_mono_s = None
        self._restart_window()

    @property
    def degraded(self) -> bool:
        return self.state in {"timestamp_lag", "rate_mismatch"}

    def observe(
        self,
        *,
        t0_us: int,
        sample_count: int,
        sample_rate_hz: int,
        receive_mono_s: float,
        missed_frames: int,
    ) -> None:
        """Account one accepted frame stamped on the server clock."""
        if sample_rate_hz <= 0 or sample_count <= 0:
            return
        last_receive_mono_s = self._last_receive_mono_s
        self._last_receive_mono_s = receive_mono_s
        if last_receive_mono_s is None or receive_mono_s - last_receive_mono_s > _INTERRUPTION_S:
            self._settled_mono_s = receive_mono_s + SENSOR_TIMING_SETTLE_S
            self._restart_window()
        if self._settled_mono_s is not None and receive_mono_s < self._settled_mono_s:
            return
        frame_end_us = t0_us + (sample_count * 1_000_000) // sample_rate_hz
        lag_us = int(receive_mono_s * 1_000_000) - frame_end_us
        if self._window_first_mono_s is None:
            # The window's first frame only anchors its receive time.
            self._window_first_mono_s = receive_mono_s
        else:
            self._window_samples += (1 + max(0, missed_frames)) * sample_count
        if self._window_min_lag_us is None or lag_us < self._window_min_lag_us:
            self._window_min_lag_us = lag_us
        if receive_mono_s - self._window_first_mono_s >= SENSOR_TIMING_WINDOW_S:
            self._close_window(
                sample_rate_hz,
                elapsed_s=receive_mono_s - self._window_first_mono_s,
                min_lag_us=self._window_min_lag_us,
            )

    def _close_window(self, sample_rate_hz: int, *, elapsed_s: float, min_lag_us: int) -> None:
        effective_rate_hz = self._window_samples / elapsed_s
        self.min_lag_us = min_lag_us
        self.effective_rate_hz = effective_rate_hz
        if min_lag_us > SENSOR_TIMING_MAX_LAG_US or min_lag_us < -_MAX_LEAD_US:
            self.state = "timestamp_lag"
        elif abs(effective_rate_hz / sample_rate_hz - 1.0) > SENSOR_TIMING_MAX_RATE_ERROR:
            self.state = "rate_mismatch"
        else:
            self.state = "ok"
        self._restart_window()

    def _restart_window(self) -> None:
        self._window_first_mono_s = None
        self._window_samples = 0
        self._window_min_lag_us = None
