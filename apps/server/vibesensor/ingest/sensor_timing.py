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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "SENSOR_TIMING_MAX_LAG_US",
    "SENSOR_TIMING_MAX_RATE_ERROR",
    "SENSOR_TIMING_WINDOW_S",
    "SensorTimingGuard",
    "SensorTimingState",
]

type SensorTimingState = Literal["unknown", "ok", "timestamp_lag", "rate_mismatch"]

SENSOR_TIMING_WINDOW_S = 20.0
# Frames are held back at most 0.75 s for retransmission (``kDataMaxFrameAgeMs``);
# a window whose fastest frame still arrives later than this is stamped behind
# real time.
SENSOR_TIMING_MAX_LAG_US = 1_000_000
# Arrival jitter over a 20 s window is well under 1 %; an untrimmed sensor
# oscillator is a few percent off.
SENSOR_TIMING_MAX_RATE_ERROR = 0.02
# A frame stamped this far ahead of its arrival means a wrong clock offset.
_MAX_LEAD_US = 250_000


@dataclass(slots=True)
class SensorTimingGuard:
    """Per-sensor timing check; ``state`` is the verdict of the last full window."""

    state: SensorTimingState = "unknown"
    min_lag_us: int | None = None
    effective_rate_hz: float | None = None
    _window_first_mono_s: float | None = None
    _window_samples: int = 0
    _window_min_lag_us: int | None = None

    def reset(self) -> None:
        """Forget the sensor's timing (it restarted or lost its clock sync)."""
        self.state = "unknown"
        self.min_lag_us = None
        self.effective_rate_hz = None
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
