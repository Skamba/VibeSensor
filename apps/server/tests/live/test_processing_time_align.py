"""Unit tests for the pure ``vibesensor.live.time_align.analysis_time_range``."""

from __future__ import annotations

import pytest

from vibesensor.live.time_align import analysis_time_range

_ATR_DEFAULTS: dict[str, object] = {
    "count": 1000,
    "last_ingest_mono_s": 100.0,
    "sample_rate_hz": 1000,
    "window_samples": 2000,
    "last_t0_us": 0,
    "samples_since_t0": 0,
}


def _atr(**overrides: object) -> tuple[float, float, bool] | None:
    """Call ``analysis_time_range`` with shared defaults + overrides."""
    return analysis_time_range(**{**_ATR_DEFAULTS, **overrides})


class TestAnalysisTimeRange:
    """Tests for the analysis time range computation."""

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"count": 0}, id="no_data"),
            pytest.param({"count": 100, "last_ingest_mono_s": 0.0}, id="no_timing"),
            pytest.param({"count": 100, "sample_rate_hz": 0}, id="zero_sample_rate"),
            pytest.param({"count": 100, "sample_rate_hz": -200}, id="negative_sample_rate"),
            pytest.param({"window_samples": 0}, id="zero_window"),
            pytest.param({"window_samples": -3}, id="negative_window"),
        ],
    )
    def test_returns_none(self, overrides: dict[str, object]) -> None:
        assert _atr(**overrides) is None

    def test_server_clock_path_preserves_partial_window_and_drift(self) -> None:
        result = _atr(
            count=450,
            last_ingest_mono_s=100.123,
        )
        assert result is not None
        start, end, synced = result
        assert synced is False
        assert end == pytest.approx(100.123)
        assert start == pytest.approx(99.673)

    def test_server_clock_path_preserves_off_by_one_sample_duration(self) -> None:
        result = _atr(count=1001)
        assert result is not None
        start, end, synced = result
        assert synced is False
        assert end == pytest.approx(100.0)
        assert start == pytest.approx(98.999)
        assert (end - start) == pytest.approx(1.001)

    def test_sensor_clock_path(self) -> None:
        result = _atr(
            last_t0_us=5_000_000,  # 5 seconds in µs
            samples_since_t0=100,
            window_samples=1000,
        )
        assert result is not None
        start, end, synced = result
        assert synced is True
        # The window ends 100 samples (0.1 s at 1 kHz) after t0 and spans 1000 samples.
        assert end == pytest.approx(5.1)
        assert start == pytest.approx(4.1)

    def test_sensor_clock_path_clamps_negative_samples_since_t0(self) -> None:
        result = _atr(last_t0_us=10_000_000, samples_since_t0=-50)
        assert result is not None
        _start, end, synced = result
        assert synced is True
        assert end == pytest.approx(10.0)

    def test_window_covers_only_the_analysed_block(self) -> None:
        result = _atr(count=5000, window_samples=2000)
        assert result is not None
        start, end, synced = result
        # The buffer holds 5 s, but the spectrum covers the newest 2000 samples.
        assert (end - start) == pytest.approx(2.0)

    @pytest.mark.parametrize("last_ingest_mono_s", [0.0, -1.0])
    def test_bad_timestamp_combinations_return_none(
        self,
        last_ingest_mono_s: float,
    ) -> None:
        assert (
            _atr(
                count=100,
                last_ingest_mono_s=last_ingest_mono_s,
                last_t0_us=5_000_000,
                samples_since_t0=450,
            )
            is None
        )
