"""Tests verifying that _plot_data() annotates vib_magnitude with driving-phase context.

Issue: _plot_data() vib_magnitude time series had no phase context.
Fix: each point in vib_magnitude is now a 3-tuple (t_s, vib_db, phase_label), and
     plots["phase_segments"] provides contiguous segment metadata for chart annotations.
"""

from __future__ import annotations

import pytest

import vibesensor.report.plot_data as plot_data_module
from vibesensor.analysis.phase_segmentation import DrivingPhase, segment_run_phases
from vibesensor.analysis.plot_data import _plot_data


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


def _make_summary(samples: list[dict], raw_sample_rate_hz: int = 200) -> dict:
    return {
        "samples": samples,
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "speed_breakdown": [],
        "findings": [],
        "speed_stats": {},
    }


class TestVibMagnitudePhaseAnnotation:
    """vib_magnitude points are 3-tuples (t_s, vib_db, phase_label)."""

    def test_each_point_has_three_elements(self) -> None:
        samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(5)]
        plots = _plot_data(_make_summary(samples))
        for point in plots["vib_magnitude"]:
            assert len(point) == 3, f"Expected 3-tuple, got {len(point)}-tuple: {point}"

    def test_phase_label_is_string(self) -> None:
        samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(5)]
        plots = _plot_data(_make_summary(samples))
        for _t, _v, phase in plots["vib_magnitude"]:
            assert isinstance(phase, str)
            assert phase in {p.value for p in DrivingPhase}

    def test_idle_samples_labelled_idle(self) -> None:
        """Samples with speed below idle threshold (3 km/h) should be labelled 'idle'."""
        samples = [_make_sample(t_s=float(i), speed_kmh=0.0) for i in range(4)]
        plots = _plot_data(_make_summary(samples))
        assert plots["vib_magnitude"], "Expected non-empty vib_magnitude"
        for _t, _v, phase in plots["vib_magnitude"]:
            assert phase == DrivingPhase.IDLE.value, f"Expected idle, got {phase!r}"

    def test_cruise_samples_labelled_cruise(self) -> None:
        """Steady-speed samples should be labelled cruise."""
        # Constant speed → no derivative → cruise
        samples = [_make_sample(t_s=float(i), speed_kmh=80.0) for i in range(6)]
        plots = _plot_data(_make_summary(samples))
        assert plots["vib_magnitude"]
        for _t, _v, phase in plots["vib_magnitude"]:
            assert phase == DrivingPhase.CRUISE.value, f"Expected cruise, got {phase!r}"

    def test_mixed_phases_present(self) -> None:
        """A run with acceleration + cruise should produce multiple distinct phase labels."""
        # First few samples: accelerating (speed rises quickly)
        accel_samples = [_make_sample(t_s=float(i), speed_kmh=float(i * 15)) for i in range(4)]
        # Then steady cruise
        cruise_samples = [_make_sample(t_s=float(4 + i), speed_kmh=60.0) for i in range(6)]
        samples = accel_samples + cruise_samples
        plots = _plot_data(_make_summary(samples))
        phases_seen = {phase for _t, _v, phase in plots["vib_magnitude"]}
        assert len(phases_seen) >= 2, f"Expected multiple phases, got: {phases_seen}"

    def test_t_s_values_are_floats(self) -> None:
        samples = [_make_sample(t_s=float(i) * 0.5, speed_kmh=60.0) for i in range(5)]
        plots = _plot_data(_make_summary(samples))
        for t, v, phase in plots["vib_magnitude"]:
            assert isinstance(t, float)
            assert isinstance(v, float)
            assert isinstance(phase, str)


class TestPhaseSegmentsOutput:
    """plots['phase_segments'] provides chart-annotation metadata."""

    def test_phase_segments_key_present(self) -> None:
        samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(4)]
        plots = _plot_data(_make_summary(samples))
        assert "phase_segments" in plots

    def test_phase_segments_is_list(self) -> None:
        samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(4)]
        plots = _plot_data(_make_summary(samples))
        assert isinstance(plots["phase_segments"], list)

    def test_phase_segments_have_required_keys(self) -> None:
        samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(4)]
        plots = _plot_data(_make_summary(samples))
        for seg in plots["phase_segments"]:
            assert "phase" in seg
            assert "start_t_s" in seg
            assert "end_t_s" in seg

    def test_phase_segment_phase_values_are_valid(self) -> None:
        samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(4)]
        plots = _plot_data(_make_summary(samples))
        valid_phases = {p.value for p in DrivingPhase}
        for seg in plots["phase_segments"]:
            assert seg["phase"] in valid_phases, f"Unknown phase: {seg['phase']!r}"

    def test_phase_segments_cover_run_time_range(self) -> None:
        """Segments collectively cover the full time range of the samples."""
        samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(6)]
        plots = _plot_data(_make_summary(samples))
        segs = plots["phase_segments"]
        assert segs, "Expected at least one segment"
        earliest = min(seg["start_t_s"] for seg in segs)
        latest = max(seg["end_t_s"] for seg in segs)
        assert earliest <= 0.0
        assert latest >= 5.0

    def test_empty_samples_yields_empty_phase_segments(self) -> None:
        plots = _plot_data(_make_summary([]))
        assert plots["phase_segments"] == []

    def test_empty_samples_yields_empty_vib_magnitude(self) -> None:
        plots = _plot_data(_make_summary([]))
        assert plots["vib_magnitude"] == []


def test_plot_data_reuses_precomputed_phase_and_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(4)]
    per_sample_phases, phase_segments = segment_run_phases(samples)

    segment_calls = 0
    noise_calls = 0

    def _count_segment_calls(rows: list[dict]) -> tuple[list, list]:  # pragma: no cover - defensive
        nonlocal segment_calls
        segment_calls += 1
        return segment_run_phases(rows)

    def _count_noise_calls(_rows: list[dict]) -> float:  # pragma: no cover - defensive
        nonlocal noise_calls
        noise_calls += 1
        return 0.02

    monkeypatch.setattr(plot_data_module, "_segment_run_phases", _count_segment_calls)
    monkeypatch.setattr(plot_data_module, "_run_noise_baseline_g", _count_noise_calls)

    _plot_data(
        _make_summary(samples),
        run_noise_baseline_g=0.02,
        per_sample_phases=per_sample_phases,
        phase_segments=phase_segments,
    )

    assert segment_calls == 0
    assert noise_calls == 0
