"""Tests for multi-sensor time-window alignment.

Covers:
- Buffer time-range computation
- Cross-sensor alignment calculation (overlap ratio, shared window)
- ``multi_spectrum_payload`` alignment metadata
- Drift / offset scenarios (stale sensor, late start, jitter)
- ``CMD_SYNC_CLOCK`` protocol round-trip
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.live.analysis_time_range import AnalysisTimeRange
from vibesensor.live.payload_types import AlignmentInfoPayload
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


def _alignment(proc: SignalProcessor, client_ids: list[str]) -> AlignmentInfoPayload:
    """Compute metrics for *client_ids* and return the live spectra alignment block."""
    for client_id in client_ids:
        proc.compute_metrics(client_id)
    return proc.multi_spectrum_payload(client_ids)["alignment"]


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
# multi-sensor alignment
# ---------------------------------------------------------------------------


class TestSensorAlignment:
    """Multi-sensor windows are aligned only when their overlap stays sufficient."""

    @pytest.mark.parametrize(
        ("s2_mono_time", "aligned", "overlap_range", "shared_duration_range"),
        [
            pytest.param(100.0, True, (0.999, 1.001), (1.9, 2.1), id="same-time"),
            pytest.param(100.5, True, (0.5, 1.0), (1.0, 2.0), id="small-offset-still-aligned"),
            pytest.param(101.5, False, (0.0, 0.5), (0.4, 0.6), id="partial-overlap"),
            pytest.param(110.0, False, (0.0, 0.0), None, id="stale-sensor-no-overlap"),
        ],
    )
    def test_two_sensor_alignment(
        self,
        s2_mono_time: float,
        aligned: bool,
        overlap_range: tuple[float, float],
        shared_duration_range: tuple[float, float] | None,
    ) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=s2_mono_time)

        alignment = _alignment(proc, ["s1", "s2"])

        assert alignment["aligned"] is aligned
        assert overlap_range[0] <= alignment["overlap_ratio"] <= overlap_range[1]
        if shared_duration_range is None:
            assert alignment["shared_window_s"] == 0.0
        else:
            low, high = shared_duration_range
            assert low <= alignment["shared_window_s"] <= high

    def test_three_sensors_aligned(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=100.1)
        _fill_sensor(proc, "s3", mono_time=100.2)
        alignment = _alignment(proc, ["s1", "s2", "s3"])
        assert alignment["aligned"] is True
        assert alignment["sensor_count"] == 3

    def test_sensor_without_data_is_excluded(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=100.0)
        alignment = _alignment(proc, ["s1", "s2", "s3"])
        assert alignment["sensor_count"] == 2
        assert alignment["aligned"] is True


# ---------------------------------------------------------------------------
# multi_spectrum_payload – alignment metadata
# ---------------------------------------------------------------------------


class TestMultiSpectrumPayloadAlignment:
    """Ensure multi-sensor spectrum payloads surface the expected alignment metadata."""

    def test_alignment_included_when_multiple_sensors(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0)
        _fill_sensor(proc, "s2", n_samples=300, mono_time=100.0)
        proc.compute_metrics("s1", sample_rate_hz=200)
        proc.compute_metrics("s2", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1", "s2"])
        assert "alignment" in payload
        assert payload["alignment"]["aligned"] is True
        assert payload["alignment"]["sensor_count"] == 2

    def test_no_alignment_key_for_single_sensor(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0)
        proc.compute_metrics("s1", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1"])
        # Only 1 sensor → no alignment block
        assert "alignment" not in payload

    def test_misaligned_sensors_flagged(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0)
        _fill_sensor(proc, "s2", n_samples=300, mono_time=110.0)
        proc.compute_metrics("s1", sample_rate_hz=200)
        proc.compute_metrics("s2", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1", "s2"])
        assert payload["alignment"]["aligned"] is False


# ---------------------------------------------------------------------------
# Drift simulation
# ---------------------------------------------------------------------------


class TestDriftSimulation:
    """Cover drift and restart scenarios that should still surface sane alignment metadata."""

    def test_gradual_drift_stays_aligned(self) -> None:
        """Sensors ingesting data with small monotonic jitter remain aligned."""
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        base_time = 1000.0
        for i in range(10):
            _fill_sensor(proc, "s1", n_samples=40, mono_time=base_time + i * 0.2)
            # s2 drifts by 5 ms per tick
            _fill_sensor(proc, "s2", n_samples=40, mono_time=base_time + i * 0.2 + i * 0.005)
        assert _alignment(proc, ["s1", "s2"])["aligned"] is True

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
# CMD_SYNC_CLOCK protocol round-trip
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Synced-clock alignment (t0_us based)
# ---------------------------------------------------------------------------


class TestSyncedClockAlignment:
    """When sensors report CMD_SYNC_CLOCK-corrected t0_us, alignment uses
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

    @pytest.mark.parametrize(
        ("s1_t0", "s2_mono", "s2_t0", "expected_aligned"),
        [
            pytest.param(50_000_000, 100.1, 50_100_000, True, id="close_timestamps"),
            pytest.param(50_000_000, 100.0, 60_000_000, False, id="large_t0_offset"),
            pytest.param(10_000_000, 100.0, 15_000_000, False, id="same_arrival_diff_sensor_ts"),
        ],
    )
    def test_synced_pair_alignment(
        self,
        s1_t0: int,
        s2_mono: float,
        s2_t0: int,
        expected_aligned: bool,
    ) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=s1_t0)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=s2_mono, t0_us=s2_t0)
        alignment = _alignment(proc, ["s1", "s2"])
        assert alignment["aligned"] is expected_aligned
        assert alignment["clock_synced"] is True
        if expected_aligned:
            assert alignment["overlap_ratio"] > 0.9

    def test_mixed_synced_unsynced_not_clock_synced(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=100.0)  # no t0_us
        assert _alignment(proc, ["s1", "s2"])["clock_synced"] is False

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

    def test_multi_spectrum_payload_reports_clock_synced(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s2", n_samples=300, mono_time=100.0, t0_us=50_100_000)
        proc.compute_metrics("s1", sample_rate_hz=200)
        proc.compute_metrics("s2", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1", "s2"])
        assert payload["alignment"]["clock_synced"] is True
        assert payload["alignment"]["aligned"] is True

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


# ---------------------------------------------------------------------------
# Wave 3 Bruno3 — analysis_time_range edge-case fixes
# ---------------------------------------------------------------------------
