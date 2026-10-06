"""Tests for per-sensor analysis time ranges.

Covers:
- Buffer time-range computation (arrival-time fallback)
- Sensor restarts and buffer flushes
- ``CMD_SYNC_CLOCK``-corrected (``t0_us``) ranges
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.live.analysis_time_range import AnalysisTimeRange
from vibesensor.live.processor import SignalProcessor

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_processor(**kwargs) -> SignalProcessor:
    defaults = {
        "sample_rate_hz": 200,
        "waveform_seconds": 2,
        "waveform_display_hz": 50,
        # The analysed block (and so each time range) is 2 s at 200 Hz.
        "fft_n": 400,
        "spectrum_max_hz": 100,
    }
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def _fill_sensor(
    proc: SignalProcessor,
    client_id: str,
    *,
    n_samples: int = 500,
    sample_rate_hz: int = 200,
    freq_hz: float = 50.0,
    mono_time: float | None = None,
    t0_us: int | None = None,
) -> None:
    """Ingest samples for a sensor, optionally pinning monotonic time and/or t0_us."""
    t = np.arange(n_samples, dtype=np.float32) / sample_rate_hz
    signal = 0.01 * np.sin(2 * np.pi * freq_hz * t)
    samples = np.column_stack([signal, signal, signal])
    if mono_time is not None:
        with patch("vibesensor.live.processor.time") as mock_time:
            mock_time.monotonic.return_value = mono_time
            proc.ingest(client_id, samples, sample_rate_hz=sample_rate_hz, t0_us=t0_us)
    else:
        proc.ingest(client_id, samples, sample_rate_hz=sample_rate_hz, t0_us=t0_us)


def _time_range(proc: SignalProcessor, client_id: str) -> AnalysisTimeRange | None:
    """Compute metrics and return the analysis window they cover."""
    proc.compute_metrics(client_id)
    return proc.latest_analysis_time_range(client_id)


# ---------------------------------------------------------------------------
# per-sensor analysis time range
# ---------------------------------------------------------------------------


class TestAnalysisTimeRange:
    """Cover per-sensor time-window derivation before overlap is computed."""

    def test_unknown_sensor_has_no_range(self) -> None:
        proc = _make_processor()
        assert _time_range(proc, "no_such_sensor") is None

    def test_single_sensor_returns_range(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, sample_rate_hz=200, mono_time=100.0)
        time_range = _time_range(proc, "s1")
        assert time_range == AnalysisTimeRange(start_s=98.0, end_s=100.0, synced=False)

    def test_range_limited_by_available_samples(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        # Only 100 samples = 0.5 s of data (less than the 2 s analysed block)
        _fill_sensor(proc, "s1", n_samples=100, sample_rate_hz=200, mono_time=50.0)
        time_range = _time_range(proc, "s1")
        assert time_range is not None
        assert time_range.end_s - time_range.start_s == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Sensor restart
# ---------------------------------------------------------------------------


class TestSensorRestart:
    """A flushed and refilled buffer reports the new session's window."""

    def test_sensor_restart_detectable(self) -> None:
        """A sensor that restarts mid-session resets its first_ingest timestamp."""
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0)
        proc.flush_client_buffer("s1")
        _fill_sensor(proc, "s1", n_samples=400, mono_time=200.0)
        time_range = _time_range(proc, "s1")
        assert time_range is not None
        assert time_range.end_s == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Synced-clock time ranges (t0_us based)
# ---------------------------------------------------------------------------


class TestSyncedClockTimeRange:
    """When sensors report CMD_SYNC_CLOCK-corrected t0_us, the time range uses
    the sensor-clock timestamps (more precise than arrival time).
    """

    @pytest.mark.parametrize(
        ("t0_us", "expected"),
        [
            pytest.param(100_000_000, True, id="with_t0_us"),
            pytest.param(None, False, id="without_t0_us"),
        ],
    )
    def test_synced_flag(self, t0_us: int | None, expected: bool) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=t0_us)
        time_range = _time_range(proc, "s1")
        assert time_range is not None
        assert time_range.synced is expected

    def test_range_ends_at_newest_sensor_sample(self) -> None:
        proc = _make_processor()
        _fill_sensor(proc, "s1", n_samples=100, mono_time=42.0, t0_us=99_000_000)
        time_range = _time_range(proc, "s1")
        assert time_range == AnalysisTimeRange(start_s=99.0, end_s=99.5, synced=True)

    def test_t0_us_reset_on_flush(self) -> None:
        proc = _make_processor()
        _fill_sensor(proc, "s1", n_samples=100, mono_time=42.0, t0_us=99_000_000)
        proc.flush_client_buffer("s1")
        assert _time_range(proc, "s1") is None
        _fill_sensor(proc, "s1", n_samples=100, mono_time=43.0)
        time_range = _time_range(proc, "s1")
        assert time_range is not None
        assert time_range.synced is False

    def test_samples_since_t0_accumulates_without_new_t0(self) -> None:
        """When successive ingests don't provide t0_us, samples_since_t0
        accumulates so the time range remains accurate.
        """
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=100, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s1", n_samples=100, mono_time=100.5)  # no t0_us
        time_range = _time_range(proc, "s1")
        assert time_range is not None
        assert time_range.end_s == pytest.approx(51.0)  # 50 s + 200 samples at 200 Hz
