"""Tests verifying that _plot_data() annotates vib_magnitude with driving-phase context.

Issue: _plot_data() vib_magnitude time series had no phase context.
Fix: each point in vib_magnitude is now a 3-tuple (t_s, vib_db, phase_label), and
     plots["phase_segments"] provides contiguous segment metadata for chart annotations.
"""

from __future__ import annotations

import pytest

import vibesensor.analysis.plot_data as plot_data_module
import vibesensor.analysis.plot_peak_table as plot_peak_table_module
import vibesensor.analysis.plot_spectrum as plot_spectrum_module
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


_VALID_PHASES = frozenset(p.value for p in DrivingPhase)
_SEGMENT_REQUIRED_KEYS = {"phase", "start_t_s", "end_t_s"}


@pytest.fixture
def cruise_plots() -> dict:
    """Pre-computed _plot_data result for a simple 6-sample cruise run at 60 km/h."""
    samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(6)]
    return _plot_data(_make_summary(samples))


class TestVibMagnitudePhaseAnnotation:
    """vib_magnitude points are 3-tuples (t_s, vib_db, phase_label)."""

    def test_each_point_is_valid_three_tuple(self, cruise_plots: dict) -> None:
        """Each point has three elements with correct types and a valid phase label."""
        for t, v, phase in cruise_plots["vib_magnitude"]:
            assert isinstance(t, float)
            assert isinstance(v, float)
            assert isinstance(phase, str)
            assert phase in _VALID_PHASES

    def test_idle_samples_labelled_idle(self) -> None:
        """Samples with speed below idle threshold (3 km/h) should be labelled 'idle'."""
        samples = [_make_sample(t_s=float(i), speed_kmh=0.0) for i in range(4)]
        plots = _plot_data(_make_summary(samples))
        assert plots["vib_magnitude"], "Expected non-empty vib_magnitude"
        for _t, _v, phase in plots["vib_magnitude"]:
            assert phase == DrivingPhase.IDLE.value, f"Expected idle, got {phase!r}"

    def test_cruise_samples_labelled_cruise(self, cruise_plots: dict) -> None:
        """Steady-speed samples should be labelled cruise."""
        assert cruise_plots["vib_magnitude"]
        for _t, _v, phase in cruise_plots["vib_magnitude"]:
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


class TestPhaseSegmentsOutput:
    """plots['phase_segments'] provides chart-annotation metadata."""

    def test_phase_segments_structure_and_validity(self, cruise_plots: dict) -> None:
        """phase_segments is a list of dicts with required keys and valid phase values."""
        segs = cruise_plots["phase_segments"]
        assert isinstance(segs, list)
        for seg in segs:
            missing = _SEGMENT_REQUIRED_KEYS - seg.keys()
            assert not missing, f"Missing keys: {missing}"
            assert seg["phase"] in _VALID_PHASES, f"Unknown phase: {seg['phase']!r}"

    def test_phase_segments_cover_run_time_range(self, cruise_plots: dict) -> None:
        """Segments collectively cover the full time range of the samples."""
        segs = cruise_plots["phase_segments"]
        assert segs, "Expected at least one segment"
        earliest = min(seg["start_t_s"] for seg in segs)
        latest = max(seg["end_t_s"] for seg in segs)
        assert earliest <= 0.0
        assert latest >= 5.0

    @pytest.mark.parametrize("key", ["phase_segments", "vib_magnitude"])
    def test_empty_samples_yields_empty_output(self, key: str) -> None:
        plots = _plot_data(_make_summary([]))
        assert plots[key] == []


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


def test_plot_data_scans_peak_samples_once_for_peak_driven_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = [_make_sample(t_s=float(i), speed_kmh=60.0) for i in range(4)]
    top_peak_calls = 0

    def _count_top_peaks(sample: dict) -> list[tuple[float, float]]:
        nonlocal top_peak_calls
        top_peak_calls += 1
        return [(float(peak["hz"]), float(peak["amp"])) for peak in sample.get("top_peaks", [])]

    def _fail_if_direct_peak_scan(_sample: dict) -> list[tuple[float, float]]:
        raise AssertionError("top_peaks should be read from the shared peak scan")

    def _fail_if_table_rescans(_samples: list[dict]) -> object:
        raise AssertionError("plot_peak_table should receive the shared peak scan")

    monkeypatch.setattr(plot_spectrum_module, "_sample_top_peaks", _count_top_peaks)
    monkeypatch.setattr(plot_peak_table_module, "scan_peak_samples", _fail_if_table_rescans)

    _plot_data(_make_summary(samples))

    assert top_peak_calls == len(samples)


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
    from vibesensor.analysis.plot_spectrum import aggregate_fft_spectrum as _aggregate_fft_spectrum

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

    two_result = dict(_aggregate_fft_spectrum(two_peaks_sample, freq_bin_hz=10.0))
    one_result = dict(_aggregate_fft_spectrum(one_peak_sample, freq_bin_hz=10.0))

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
