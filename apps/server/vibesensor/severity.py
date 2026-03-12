"""Severity-bucket state tracking with hysteresis and persistence.

``SeverityTracker`` is a state object that tracks vibration severity over
successive ticks, applying promotion/decay thresholds, multi-sensor
corroboration, and frequency-guard persistence.

The legacy ``severity_from_peak`` function is kept as a thin wrapper for
backward compatibility with existing callers and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from vibesensor.strength_bands import (
    DECAY_TICKS,
    HYSTERESIS_DB,
    PERSISTENCE_TICKS,
    band_by_key,
    band_rank,
    bucket_for_strength,
)

from .constants import MULTI_SENSOR_CORROBORATION_DB
from .domain_models import as_float_or_none


class SeverityTrackerState(TypedDict):
    current_bucket: str | None
    pending_bucket: str | None
    consecutive_up: int
    consecutive_down: int
    last_confirmed_hz: float | None


class SeverityResult(TypedDict):
    key: str | None
    db: float
    state: SeverityTrackerState


@dataclass(slots=True)
class SeverityTracker:
    """Stateful severity-bucket tracker with hysteresis and persistence.

    Encapsulates the promotion/decay state machine that was previously
    spread across a function with nested closures and a TypedDict bag.
    """

    current_bucket: str | None = None
    pending_bucket: str | None = None
    consecutive_up: int = 0
    consecutive_down: int = 0
    last_confirmed_hz: float | None = None

    # -- construction -------------------------------------------------------

    @staticmethod
    def from_state(state: SeverityTrackerState | None) -> SeverityTracker:
        """Reconstruct from a previously returned state dict."""
        if state is None:
            return SeverityTracker()
        return SeverityTracker(
            current_bucket=state.get("current_bucket"),
            pending_bucket=state.get("pending_bucket"),
            consecutive_up=int(state.get("consecutive_up", 0)),
            consecutive_down=int(state.get("consecutive_down", 0)),
            last_confirmed_hz=as_float_or_none(state.get("last_confirmed_hz")),
        )

    # -- serialisation ------------------------------------------------------

    def to_state(self) -> SeverityTrackerState:
        """Export the current state as a TypedDict for serialisation."""
        return {
            "current_bucket": self.current_bucket,
            "pending_bucket": self.pending_bucket,
            "consecutive_up": self.consecutive_up,
            "consecutive_down": self.consecutive_down,
            "last_confirmed_hz": self.last_confirmed_hz,
        }

    # -- state machine reset ------------------------------------------------

    def _reset(self, *, new_bucket: str | None = None) -> None:
        """Reset all counters and optionally set a new current bucket."""
        self.current_bucket = new_bucket
        self.pending_bucket = None
        self.consecutive_up = 0
        self.consecutive_down = 0
        self.last_confirmed_hz = None

    # -- tick ---------------------------------------------------------------

    def tick(
        self,
        *,
        vibration_strength_db: float,
        sensor_count: int,
        peak_hz: float | None = None,
        persistence_freq_bin_hz: float | None = None,
    ) -> SeverityResult:
        """Advance the tracker by one measurement and return the result.

        Applies hysteresis, persistence, and multi-sensor corroboration.
        """
        corroboration = MULTI_SENSOR_CORROBORATION_DB if sensor_count >= 2 else 0.0
        adjusted_db = float(vibration_strength_db) + corroboration
        candidate_bucket_raw = bucket_for_strength(adjusted_db)
        candidate_bucket = None if candidate_bucket_raw == "l0" else candidate_bucket_raw
        peak_hz_value = as_float_or_none(peak_hz)
        freq_bin_hz = as_float_or_none(persistence_freq_bin_hz)
        freq_guard_enabled = (
            peak_hz_value is not None and freq_bin_hz is not None and freq_bin_hz > 0
        )

        if candidate_bucket is None:
            self._handle_no_candidate(adjusted_db)
            return self._result(adjusted_db)

        if self.current_bucket is None:
            self._try_promote(candidate_bucket, peak_hz_value, freq_bin_hz, freq_guard_enabled)
            return self._result(adjusted_db)

        current_rank = band_rank(str(self.current_bucket))
        candidate_rank = band_rank(str(candidate_bucket))
        if candidate_rank > current_rank:
            self._try_promote(candidate_bucket, peak_hz_value, freq_bin_hz, freq_guard_enabled)
        elif candidate_rank < current_rank:
            self._handle_decay(adjusted_db, candidate_bucket)
        else:
            self.pending_bucket = None
            self.consecutive_up = 0
            self.last_confirmed_hz = None

        return self._result(adjusted_db)

    # -- internal state transitions -----------------------------------------

    def _handle_no_candidate(self, adjusted_db: float) -> None:
        """Handle tick where candidate is below l0."""
        if self.current_bucket is not None:
            current_band = band_by_key(str(self.current_bucket))
            if current_band and current_band.exceeds_with_hysteresis(adjusted_db, HYSTERESIS_DB):
                self.consecutive_down += 1
                if self.consecutive_down >= DECAY_TICKS:
                    self._reset()
            else:
                self.consecutive_down = 0

    def _handle_decay(self, adjusted_db: float, candidate_bucket: str) -> None:
        """Handle tick where candidate is ranked below the current bucket."""
        current_band = band_by_key(str(self.current_bucket))
        if current_band and current_band.exceeds_with_hysteresis(adjusted_db, HYSTERESIS_DB):
            self.consecutive_down += 1
            if self.consecutive_down >= DECAY_TICKS:
                self._reset(new_bucket=candidate_bucket)
        else:
            self.consecutive_down = 0

    def _advance_pending(
        self,
        candidate: str,
        peak_hz_value: float | None,
        freq_bin_hz: float | None,
        freq_guard_enabled: bool,
    ) -> None:
        """Advance the pending-bucket counter."""
        if self.pending_bucket == candidate:
            if freq_guard_enabled:
                assert peak_hz_value is not None and freq_bin_hz is not None
                if (
                    self.last_confirmed_hz is not None
                    and abs(float(peak_hz_value) - self.last_confirmed_hz) > float(freq_bin_hz)
                ):
                    self.consecutive_up = 1
                    self.last_confirmed_hz = peak_hz_value
                    return
                if self.last_confirmed_hz is None:
                    self.last_confirmed_hz = peak_hz_value
            self.consecutive_up += 1
            return

        self.pending_bucket = candidate
        self.consecutive_up = 1
        self.last_confirmed_hz = peak_hz_value if freq_guard_enabled else None

    def _try_promote(
        self,
        candidate: str,
        peak_hz_value: float | None,
        freq_bin_hz: float | None,
        freq_guard_enabled: bool,
    ) -> None:
        """Advance pending bucket and promote if persistence threshold is met."""
        self.consecutive_down = 0
        self._advance_pending(candidate, peak_hz_value, freq_bin_hz, freq_guard_enabled)
        if self.consecutive_up >= PERSISTENCE_TICKS:
            self.current_bucket = candidate
            self.pending_bucket = None
            self.consecutive_up = 0
            if freq_guard_enabled:
                self.last_confirmed_hz = peak_hz_value

    def _result(self, adjusted_db: float) -> SeverityResult:
        """Build the standard result dict."""
        return {"key": self.current_bucket, "db": adjusted_db, "state": self.to_state()}


# ---------------------------------------------------------------------------
# Backward-compatible functional API
# ---------------------------------------------------------------------------


def severity_from_peak(
    *,
    vibration_strength_db: float,
    sensor_count: int,
    prior_state: SeverityTrackerState | None = None,
    peak_hz: float | None = None,
    persistence_freq_bin_hz: float | None = None,
) -> SeverityResult:
    """Compute the severity bucket and updated state for a peak measurement.

    Thin wrapper around :class:`SeverityTracker` that preserves the original
    functional signature used by callers and tests.
    """
    tracker = SeverityTracker.from_state(prior_state)
    return tracker.tick(
        vibration_strength_db=vibration_strength_db,
        sensor_count=sensor_count,
        peak_hz=peak_hz,
        persistence_freq_bin_hz=persistence_freq_bin_hz,
    )
