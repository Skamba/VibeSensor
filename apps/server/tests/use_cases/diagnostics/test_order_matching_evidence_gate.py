"""Focused regressions for time-aware order-evidence gating."""

from __future__ import annotations

from test_support.report_helpers import diagnostics_context

from vibesensor.domain import OrderMatchObservation, VibrationSource
from vibesensor.shared.boundaries.sensor_frame_codec import normalize_sensor_frames
from vibesensor.use_cases.diagnostics.orders.matching import OrderMatchAccumulator
from vibesensor.use_cases.diagnostics.orders.physics import OrderHypothesis
from vibesensor.use_cases.diagnostics.orders.pipeline import (
    OrderAnalysisRequest,
    OrderAnalysisSession,
)


def _make_accumulator(
    *,
    possible: int,
    matched: int,
    sample_indices: tuple[int, ...],
    matched_speed_bins: dict[str, int] | None = None,
    predicted_vals: list[float] | None = None,
    measured_vals: list[float] | None = None,
) -> OrderMatchAccumulator:
    if predicted_vals is None:
        predicted_vals = [50.0 + float(i) for i in range(matched)]
    if measured_vals is None:
        measured_vals = [value + 0.1 for value in predicted_vals]

    matched_points = [
        OrderMatchObservation(
            predicted_hz=predicted_vals[idx],
            matched_hz=measured_vals[idx],
            rel_error=abs(measured_vals[idx] - predicted_vals[idx]) / predicted_vals[idx],
            amp=0.05,
            location="front_left",
            speed_kmh=60.0 + float(idx),
            t_s=0.25 * float(sample_indices[idx]),
        )
        for idx in range(matched)
    ]
    speed_bins = matched_speed_bins or {"60-70": matched}
    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=[0.05] * matched,
        matched_floor=[0.005] * matched,
        rel_errors=[0.01] * matched,
        predicted_vals=predicted_vals,
        measured_vals=measured_vals,
        matched_points=matched_points,
        ref_sources={"speed+tire"},
        possible_by_speed_bin={"60-70": possible},
        matched_by_speed_bin=speed_bins,
        possible_by_phase={},
        matched_by_phase={},
        possible_by_location={"front_left": possible},
        matched_by_location={"front_left": matched},
        has_phases=False,
        compliance=1.0,
        matched_sample_indices=sample_indices,
    )


def _session(
    steady_speed: bool,
    *,
    feature_interval_s: float | None = 0.25,
) -> OrderAnalysisSession:
    return OrderAnalysisSession(
        OrderAnalysisRequest(
            context=diagnostics_context(feature_interval_s=feature_interval_s),
            samples=normalize_sensor_frames(
                [{"speed_kmh": 60.0, "top_peaks": [{"hz": 10.0, "amp": 0.05}]}],
            ),
            speed_sufficient=True,
            steady_speed=steady_speed,
            speed_stddev_kmh=0.3 if steady_speed else 6.0,
            tire_circumference_m=2.0,
            engine_ref_sufficient=True,
            raw_sample_rate_hz=800.0,
            connected_locations={"front_left"},
            lang="en",
        ),
    )


class TestOrderMatchEvidenceGate:
    def test_rejects_short_overlap_burst_even_when_raw_counts_pass(self) -> None:
        match = _make_accumulator(
            possible=6,
            matched=4,
            sample_indices=(0, 1, 2, 3),
        )

        assert match.is_eligible(feature_interval_s=0.25, steady_speed=True) is False

    def test_accepts_steady_state_when_duration_and_contiguity_are_sufficient(self) -> None:
        match = _make_accumulator(
            possible=16,
            matched=8,
            sample_indices=(4, 5, 6, 7, 8, 9, 10, 11),
        )

        assert match.is_eligible(feature_interval_s=0.25, steady_speed=True) is True

    def test_rejects_when_contiguous_streak_is_too_short(self) -> None:
        match = _make_accumulator(
            possible=20,
            matched=8,
            sample_indices=(0, 1, 2, 8, 9, 10, 16, 17),
            matched_speed_bins={"50-60": 4, "60-70": 4},
        )

        assert match.is_eligible(feature_interval_s=0.25, steady_speed=True) is False

    def test_rejects_variable_speed_single_bin_without_broad_tracking(self) -> None:
        match = _make_accumulator(
            possible=20,
            matched=8,
            sample_indices=(4, 5, 6, 7, 8, 9, 10, 11),
            matched_speed_bins={"60-70": 8},
            predicted_vals=[50.0] * 8,
            measured_vals=[50.1] * 8,
        )

        assert match.is_eligible(feature_interval_s=0.25, steady_speed=False) is False

    def test_accepts_variable_speed_with_multiple_matched_speed_bins(self) -> None:
        match = _make_accumulator(
            possible=20,
            matched=8,
            sample_indices=(4, 5, 6, 7, 8, 9, 10, 11),
            matched_speed_bins={"50-60": 4, "60-70": 4},
        )

        assert match.is_eligible(feature_interval_s=0.25, steady_speed=False) is True

    def test_accepts_variable_speed_with_strong_frequency_tracking(self) -> None:
        match = _make_accumulator(
            possible=20,
            matched=8,
            sample_indices=(4, 5, 6, 7, 8, 9, 10, 11),
            matched_speed_bins={"60-70": 8},
            predicted_vals=[50.0, 50.5, 51.0, 51.5, 52.0, 52.5, 53.0, 53.5],
            measured_vals=[50.1, 50.6, 51.1, 51.6, 52.1, 52.6, 53.1, 53.6],
        )

        assert match.is_eligible(feature_interval_s=0.25, steady_speed=False) is True


class TestOrderAnalysisSessionEvidenceGate:
    def test_session_passes_feature_interval_and_steady_speed_into_match_gate(
        self,
        monkeypatch,
    ) -> None:
        captured: dict[str, object] = {}

        class FakeAccumulator:
            def is_eligible(self, **kwargs) -> bool:
                captured.update(kwargs)
                return False

        monkeypatch.setattr(
            "vibesensor.use_cases.diagnostics.orders.pipeline.match_samples_for_hypothesis",
            lambda *args, **kwargs: FakeAccumulator(),
        )

        session = _session(steady_speed=True, feature_interval_s=0.25)
        hypothesis = OrderHypothesis(
            key="wheel_1x",
            suspected_source=VibrationSource.WHEEL_TIRE,
            order_label_base="wheel",
            order=1.0,
        )

        assert session._test_hypothesis(hypothesis) is None
        assert captured == {"feature_interval_s": 0.25, "steady_speed": True}
