"""Tests verifying that _plot_data() annotates vib_magnitude with driving-phase context.

Issue: _plot_data() vib_magnitude time series had no phase context.
Fix: each point in vib_magnitude is now a 3-tuple (t_s, vib_db, phase_label), and
     plots["phase_segments"] provides contiguous segment metadata for chart annotations.
"""

from __future__ import annotations

import pytest

import vibesensor.use_cases.diagnostics.plots as plots_module
from vibesensor.shared.boundaries.sensor_frame_codec import sensor_frames_from_rows
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase, segment_run_phases
from vibesensor.use_cases.diagnostics.plots import _plot_data


def _make_sample(
    t_s: float,
    speed_kmh: float,
    vib_db: float = 20.0,
) -> dict:
    return {
        "record_type": "sample",
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "vibration_strength_db": vib_db,
        "dominant_freq_hz": 14.0,
        "top_peaks": [{"hz": 14.0, "amp": 0.05}],
        "accel_x_g": 0.05,
        "accel_y_g": 0.05,
        "accel_z_g": 0.05,
    }


def _samples_at_speed(
    count: int,
    *,
    speed_kmh: float,
    start_t_s: float = 0.0,
    vib_db: float = 20.0,
) -> list[dict]:
    return [
        _make_sample(
            t_s=start_t_s + float(i),
            speed_kmh=speed_kmh,
            vib_db=vib_db,
        )
        for i in range(count)
    ]


def _build_plot_data(
    samples: list[dict],
    *,
    raw_sample_rate_hz: int = 200,
    run_noise_baseline_g: float | None = None,
    per_sample_phases: list[DrivingPhase] | None = None,
    phase_segments: list | None = None,
):
    return _plot_data(
        samples=sensor_frames_from_rows(samples),
        speed_breakdown=[],
        phase_speed_breakdown=[],
        findings=(),
        raw_sample_rate_hz=float(raw_sample_rate_hz),
        steady_speed=False,
        run_noise_baseline_g=run_noise_baseline_g,
        per_sample_phases=per_sample_phases,
        phase_segments=phase_segments,
    )


_VALID_PHASES = frozenset(p.value for p in DrivingPhase)
_SEGMENT_REQUIRED_KEYS = {"phase", "start_t_s", "end_t_s"}


@pytest.fixture
def cruise_plots():
    """Pre-computed _plot_data result for a simple 6-sample cruise run at 60 km/h."""
    return _build_plot_data(_samples_at_speed(6, speed_kmh=60.0))


class TestVibMagnitudePhaseAnnotation:
    """vib_magnitude points are 3-tuples (t_s, vib_db, phase_label)."""

    def test_each_point_is_valid_three_tuple(self, cruise_plots) -> None:
        """Each point has three elements with correct types and a valid phase label."""
        for t, v, phase in cruise_plots.vib_magnitude:
            assert isinstance(t, float)
            assert isinstance(v, float)
            assert isinstance(phase, str)
            assert phase in _VALID_PHASES

    def test_idle_samples_labelled_idle(self) -> None:
        """Samples with speed below idle threshold (3 km/h) should be labelled 'idle'."""
        plots = _build_plot_data(_samples_at_speed(4, speed_kmh=0.0))
        assert plots.vib_magnitude, "Expected non-empty vib_magnitude"
        for _t, _v, phase in plots.vib_magnitude:
            assert phase == DrivingPhase.IDLE.value, f"Expected idle, got {phase!r}"

    def test_cruise_samples_labelled_cruise(self, cruise_plots) -> None:
        """Steady-speed samples should be labelled cruise."""
        assert cruise_plots.vib_magnitude
        for _t, _v, phase in cruise_plots.vib_magnitude:
            assert phase == DrivingPhase.CRUISE.value, f"Expected cruise, got {phase!r}"

    def test_mixed_phases_present(self) -> None:
        """A run with acceleration + cruise should produce multiple distinct phase labels."""
        # First few samples: accelerating (speed rises quickly)
        accel_samples = [_make_sample(t_s=float(i), speed_kmh=float(i * 15)) for i in range(4)]
        # Then steady cruise
        cruise_samples = [_make_sample(t_s=float(4 + i), speed_kmh=60.0) for i in range(6)]
        samples = accel_samples + cruise_samples
        plots = _build_plot_data(samples)
        phases_seen = {phase for _t, _v, phase in plots.vib_magnitude}
        assert len(phases_seen) >= 2, f"Expected multiple phases, got: {phases_seen}"


class TestPhaseSegmentsOutput:
    """plots['phase_segments'] provides chart-annotation metadata."""

    def test_phase_segments_structure_and_validity(self, cruise_plots) -> None:
        """phase_segments is a list of typed rows with valid phase values."""
        segs = cruise_plots.phase_segments
        assert isinstance(segs, list)
        for seg in segs:
            for attr in _SEGMENT_REQUIRED_KEYS:
                assert hasattr(seg, attr), f"Missing attr: {attr}"
            assert seg.phase in _VALID_PHASES, f"Unknown phase: {seg.phase!r}"

    def test_phase_segments_cover_run_time_range(self, cruise_plots) -> None:
        """Segments collectively cover the full time range of the samples."""
        segs = cruise_plots.phase_segments
        assert segs, "Expected at least one segment"
        earliest = min(seg.start_t_s for seg in segs)
        latest = max(seg.end_t_s for seg in segs)
        assert earliest <= 0.0
        assert latest >= 5.0

    @pytest.mark.parametrize("attr_name", ["phase_segments", "vib_magnitude"])
    def test_empty_samples_yields_empty_output(self, attr_name: str) -> None:
        plots = _build_plot_data([])
        assert getattr(plots, attr_name) == []


def test_plot_data_reuses_precomputed_phase_and_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = _samples_at_speed(4, speed_kmh=60.0)
    typed_samples = sensor_frames_from_rows(samples)
    per_sample_phases, phase_segments = segment_run_phases(typed_samples)

    segment_calls = 0
    noise_calls = 0

    def _count_segment_calls(rows: list) -> tuple[list, list]:  # pragma: no cover - defensive
        nonlocal segment_calls
        segment_calls += 1
        return segment_run_phases(rows)

    def _count_noise_calls(_rows: list[dict]) -> float:  # pragma: no cover - defensive
        nonlocal noise_calls
        noise_calls += 1
        return 0.02

    monkeypatch.setattr(plots_module, "segment_run_phases", _count_segment_calls)
    monkeypatch.setattr(plots_module, "_run_noise_baseline_g", _count_noise_calls)

    _build_plot_data(
        samples,
        run_noise_baseline_g=0.02,
        per_sample_phases=per_sample_phases,
        phase_segments=phase_segments,
    )

    assert segment_calls == 0
    assert noise_calls == 0


def test_plot_data_scans_peak_samples_once_for_peak_driven_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = _samples_at_speed(4, speed_kmh=60.0)
    scan_calls = 0
    original_scan = plots_module.scan_peak_samples

    def _counting_scan(s: list) -> object:
        nonlocal scan_calls
        scan_calls += 1
        return original_scan(s)

    monkeypatch.setattr(plots_module, "scan_peak_samples", _counting_scan)

    _build_plot_data(samples)

    assert scan_calls == 1, f"scan_peak_samples called {scan_calls} times, expected 1"


# ---------------------------------------------------------------------------
# Regression: _aggregate_fft_spectrum presence_ratio > 1 when a single sample
# contributes two peaks into the same frequency bin.
# ---------------------------------------------------------------------------


def test_aggregate_fft_spectrum_presence_ratio_clamped_to_one() -> None:
    """Two peaks from the same sample that bin together must not exceed presence_ratio=1.

    At freq_bin_hz=10 Hz, peaks at 42 Hz and 47 Hz both fall in the 40–50 Hz
    bin (bin_center = 45 Hz). Previously len(amps)=2 / n_samples=1 = 2.0 gave
    a persistence score inflated by 4× relative to a single-peak sample.
    """
    from vibesensor.use_cases.diagnostics.spectrogram import (
        aggregate_fft_spectrum as _aggregate_fft_spectrum,
    )

    # Two co-binned peaks from one sample — should behave like presence_ratio=1.
    two_peaks_sample = [
        {
            "vibration_strength_db": 20.0,
            "top_peaks": [
                # Both bin to center 45 Hz at freq_bin_hz=10
                {"hz": 42.0, "amp": 0.1},
                {"hz": 47.0, "amp": 0.12},
            ],
        },
    ]
    # Baseline: single peak at same p95 amplitude from one sample.
    one_peak_sample = [
        {
            "vibration_strength_db": 20.0,
            "top_peaks": [{"hz": 45.0, "amp": 0.12}],
        },
    ]

    two_result = dict(
        _aggregate_fft_spectrum(sensor_frames_from_rows(two_peaks_sample), freq_bin_hz=10.0),
    )
    one_result = dict(
        _aggregate_fft_spectrum(sensor_frames_from_rows(one_peak_sample), freq_bin_hz=10.0),
    )

    # Both produce a single bin near 45 Hz with presence_ratio=1 after clamping.
    # Without clamping, two_result score would be 4× one_result score (2²=4).
    assert len(two_result) == 1, "expected a single 45 Hz bin"
    assert len(one_result) == 1, "expected a single 45 Hz bin"
    # After clamping, two co-binned peaks should NOT produce a score 4× larger.
    # The score may differ slightly (p95 of [0.1, 0.12] vs [0.12]) but
    # the 4× inflation from unclamped presence_ratio=2 would be unmistakable.
    two_score = next(iter(two_result.values()))
    one_score = next(iter(one_result.values()))
    assert two_score < one_score * 2.5, (  # far less than 4× inflation
        f"two co-binned peaks score {two_score:.3f} is suspiciously > 2.5× "
        f"single-peak score {one_score:.3f}; presence_ratio may be unclamped"
    )
