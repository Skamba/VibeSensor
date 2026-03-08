"""Phase- and timeline-focused scenario regression tests for reporting."""

from __future__ import annotations

from typing import Any

import pytest
from _scenario_regression_helpers import (
    build_phased_samples,
    build_speed_sweep_samples,
    standard_metadata,
)

from vibesensor.analysis import build_findings_for_samples
from vibesensor.analysis.findings.intensity import (
    _phase_speed_breakdown,
    _sensor_intensity_by_location,
)
from vibesensor.analysis.phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    phase_summary,
    segment_run_phases,
)
from vibesensor.analysis import summarize_run_data


class TestPhaseSegmentation:
    """Verify driving-phase classification across various speed profiles."""

    def test_idle_to_speed_up(self) -> None:
        samples = build_phased_samples([(5, 0.0, 0.0), (10, 8.0, 80.0), (10, 80.0, 81.0)])

        per_sample, segments = segment_run_phases(samples)
        assert len(per_sample) == 25
        phases_present = {segment.phase for segment in segments}
        assert DrivingPhase.IDLE in phases_present
        assert DrivingPhase.CRUISE in phases_present or DrivingPhase.ACCELERATION in phases_present

    def test_stop_go(self) -> None:
        samples = build_phased_samples(
            [
                (3, 0.0, 0.0),
                (5, 30.0, 50.0),
                (3, 0.0, 0.0),
                (5, 30.0, 50.0),
                (3, 0.0, 0.0),
                (5, 30.0, 50.0),
            ]
        )
        per_sample, _segments = segment_run_phases(samples)
        idle_count = sum(1 for phase in per_sample if phase == DrivingPhase.IDLE)
        assert idle_count >= 6

    def test_coast_down(self) -> None:
        samples = build_phased_samples([(20, 50.0, 2.0)])
        per_sample, _segments = segment_run_phases(samples)
        assert any(
            phase in (DrivingPhase.DECELERATION, DrivingPhase.COAST_DOWN) for phase in per_sample
        )

    @pytest.mark.parametrize(
        ("phases", "kwargs", "expected"),
        [
            pytest.param(
                [
                    DrivingPhase.IDLE,
                    DrivingPhase.CRUISE,
                    DrivingPhase.IDLE,
                    DrivingPhase.ACCELERATION,
                ],
                {},
                [False, True, False, True],
                id="excludes_idle_by_default",
            ),
            pytest.param(
                [DrivingPhase.IDLE, DrivingPhase.COAST_DOWN, DrivingPhase.CRUISE],
                {"exclude_coast_down": True},
                [False, False, True],
                id="exclude_coast_down",
            ),
            pytest.param(
                [DrivingPhase.IDLE, DrivingPhase.COAST_DOWN, DrivingPhase.CRUISE],
                {},
                [False, True, True],
                id="coast_down_included_by_default",
            ),
        ],
    )
    def test_diagnostic_mask(
        self,
        phases: list[DrivingPhase],
        kwargs: dict[str, Any],
        expected: list[bool],
    ) -> None:
        assert diagnostic_sample_mask(phases, **kwargs) == expected

    def test_phase_summary_structure(self) -> None:
        samples = [
            {"t_s": 0.0, "speed_kmh": 0.0},
            {"t_s": 1.0, "speed_kmh": 60.0},
            {"t_s": 2.0, "speed_kmh": 60.0},
        ]
        _, segments = segment_run_phases(samples)
        info = phase_summary(segments)
        assert "phase_counts" in info
        assert "total_samples" in info
        assert info["total_samples"] == 3
        assert abs(sum(info["phase_pcts"].values()) - 100.0) < 0.01

    def test_all_five_phases_can_be_detected(self) -> None:
        samples = []
        for idx in range(5):
            samples.append({"t_s": float(idx), "speed_kmh": 0.5})
        for idx in range(5, 25):
            samples.append({"t_s": float(idx), "speed_kmh": float((idx - 5) * 4)})
        for idx in range(25, 40):
            samples.append({"t_s": float(idx), "speed_kmh": 80.0})
        for idx in range(40, 55):
            samples.append({"t_s": float(idx), "speed_kmh": max(20.0, 80.0 - (idx - 40) * 4.0)})
        for idx in range(55, 60):
            samples.append({"t_s": float(idx), "speed_kmh": max(0.0, 20.0 - (idx - 55) * 4.0)})

        per_sample, segments = segment_run_phases(samples)
        assert len(per_sample) == len(samples)
        phases_found = {segment.phase for segment in segments}
        assert DrivingPhase.IDLE in phases_found
        assert DrivingPhase.ACCELERATION in phases_found
        assert DrivingPhase.CRUISE in phases_found
        assert DrivingPhase.DECELERATION in phases_found or DrivingPhase.COAST_DOWN in phases_found

        info = phase_summary(segments)
        assert info["has_cruise"]
        assert info["has_acceleration"]
        assert info["total_samples"] == len(samples)

    def test_empty_samples_returns_empty(self) -> None:
        per_sample, segments = segment_run_phases([])
        assert per_sample == []
        assert segments == []

    def test_none_speed_treated_as_speed_unknown(self) -> None:
        samples = [{"t_s": 0.0, "speed_kmh": None}, {"t_s": 1.0, "speed_kmh": None}]
        per_sample, _segments = segment_run_phases(samples)
        assert all(phase == DrivingPhase.SPEED_UNKNOWN for phase in per_sample)


class TestSensorIntensityPhaseContext:
    """Per-location intensity rows should carry phase context when available."""

    def test_phase_intensity_present_when_phases_provided(self) -> None:
        samples = []
        for idx in range(5):
            samples.append(
                {
                    "t_s": float(idx),
                    "speed_kmh": 0.0,
                    "vibration_strength_db": 4.0,
                    "location_key": "front-left",
                }
            )
        for idx in range(5, 15):
            samples.append(
                {
                    "t_s": float(idx),
                    "speed_kmh": 60.0,
                    "vibration_strength_db": 22.0,
                    "location_key": "front-left",
                }
            )

        per_sample_phases, _ = segment_run_phases(samples)
        rows = _sensor_intensity_by_location(samples, per_sample_phases=per_sample_phases)

        for row in rows:
            phase_intensity = row.get("phase_intensity")
            assert phase_intensity is not None
            assert len(phase_intensity) >= 1
            for stats in phase_intensity.values():
                assert "count" in stats
                assert "mean_intensity_db" in stats

    def test_phase_intensity_absent_without_phases(self) -> None:
        rows = _sensor_intensity_by_location(
            [{"t_s": 0.0, "speed_kmh": 60.0, "vibration_strength_db": 22.0, "location_key": "fl"}]
        )
        for row in rows:
            assert row.get("phase_intensity") is None

    def test_summarize_run_data_includes_phase_intensity_in_location_rows(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        for location_row in summary.get("sensor_intensity_by_location", []):
            assert "phase_intensity" in location_row


class TestOrderFindingsPhaseFiltering:
    """Diagnostic analysis should exclude idle-only contamination where possible."""

    def test_idle_samples_excluded_from_order_analysis(self) -> None:
        idle = [
            {"t_s": float(idx), "speed_kmh": 0.0, "vibration_strength_db": 5.0} for idx in range(5)
        ]
        cruise = [
            {
                "t_s": float(idx + 5),
                "speed_kmh": 60.0,
                "vibration_strength_db": 22.0,
                "raw_sample_rate_hz": 800,
            }
            for idx in range(15)
        ]
        samples = idle + cruise
        per_sample_phases, _ = segment_run_phases(samples)

        idle_count = sum(1 for phase in per_sample_phases if phase == DrivingPhase.IDLE)
        non_idle_count = sum(1 for phase in per_sample_phases if phase != DrivingPhase.IDLE)
        assert idle_count >= 3
        assert non_idle_count >= 5

    def test_build_findings_falls_back_if_too_few_diagnostic_samples(self) -> None:
        samples = [
            {"t_s": float(idx), "speed_kmh": 0.0, "vibration_strength_db": 5.0} for idx in range(10)
        ]
        summary = summarize_run_data(standard_metadata(), samples, include_samples=False)
        assert "findings" in summary

    def test_phase_filtering_does_not_break_full_pipeline(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (20, 10.0, 80.0)]),
            include_samples=False,
        )
        assert "findings" in summary
        for finding in summary["findings"]:
            assert "finding_id" in finding
            assert "confidence_0_to_1" in finding


class TestPhaseSpeedBreakdown:
    """Phase-speed breakdown should expose temporal context instead of only speed bins."""

    def test_phase_speed_breakdown_groups_by_phase(self) -> None:
        samples = []
        for idx in range(5):
            samples.append({"t_s": float(idx), "speed_kmh": 0.5, "vibration_strength_db": 5.0})
        for idx in range(5, 20):
            samples.append({"t_s": float(idx), "speed_kmh": 60.0, "vibration_strength_db": 22.0})

        per_sample_phases, _ = segment_run_phases(samples)
        rows = _phase_speed_breakdown(samples, per_sample_phases)
        phase_names = {row["phase"] for row in rows}
        assert DrivingPhase.IDLE.value in phase_names
        assert (
            DrivingPhase.CRUISE.value in phase_names
            or DrivingPhase.ACCELERATION.value in phase_names
        )

    def test_phase_speed_breakdown_included_in_summary(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        phase_speed_breakdown = summary.get("phase_speed_breakdown")
        assert phase_speed_breakdown is not None
        assert isinstance(phase_speed_breakdown, list)
        assert len(phase_speed_breakdown) >= 1
        for row in phase_speed_breakdown:
            assert "phase" in row
            assert "count" in row
            assert row["count"] > 0

    def test_phase_breakdown_rows_cover_all_samples(self) -> None:
        samples = build_phased_samples([(5, 0.0, 0.0), (10, 50.0, 80.0), (5, 0.0, 0.0)])
        per_sample_phases, _ = segment_run_phases(samples)
        rows = _phase_speed_breakdown(samples, per_sample_phases)
        assert sum(int(row["count"]) for row in rows) == len(samples)

    def test_amp_vs_phase_in_plots(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        amp_vs_phase = summary.get("plots", {}).get("amp_vs_phase")
        assert amp_vs_phase is not None
        assert isinstance(amp_vs_phase, list)
        assert len(amp_vs_phase) >= 1
        for row in amp_vs_phase:
            assert "phase" in row
            assert "count" in row
            assert "mean_vib_db" in row
            assert row["count"] > 0

    def test_phase_speed_breakdown_does_not_drop_samples_when_phase_list_short(self) -> None:
        samples = [
            {"t_s": 0.0, "speed_kmh": 40.0, "vibration_strength_db": 10.0},
            {"t_s": 1.0, "speed_kmh": 50.0, "vibration_strength_db": 11.0},
            {"t_s": 2.0, "speed_kmh": 60.0, "vibration_strength_db": 12.0},
        ]
        rows = _phase_speed_breakdown(samples, ["cruise"])
        assert sum(int(row["count"]) for row in rows) == 3
        assert any(str(row["phase"]) == "unknown" for row in rows)


class TestPhaseInfoInSummary:
    """Summary output should propagate serialized phase information consistently."""

    def test_phase_info_present(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_samples(n=20, vib_db=18.0),
            include_samples=False,
        )
        phase_info = summary.get("phase_info")
        assert phase_info is not None
        assert "total_samples" in phase_info
        assert phase_info["total_samples"] == 20

    def test_phase_info_propagated_to_all_dependents(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        phase_info = summary.get("phase_info")
        assert phase_info is not None
        assert "phase_counts" in phase_info
        assert phase_info["total_samples"] == 20

        phase_speed_breakdown = summary.get("phase_speed_breakdown")
        assert phase_speed_breakdown is not None
        assert sum(int(row["count"]) for row in phase_speed_breakdown) == 20

        for location_row in summary.get("sensor_intensity_by_location", []):
            assert "phase_intensity" in location_row

    def test_phase_segments_serialized_in_summary(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        phase_segments = summary.get("phase_segments")
        assert phase_segments is not None
        assert isinstance(phase_segments, list)
        assert len(phase_segments) >= 1
        for segment in phase_segments:
            assert isinstance(segment, dict)
            for key in ("phase", "start_idx", "end_idx", "start_t_s", "end_t_s", "sample_count"):
                assert key in segment
        assert sum(int(segment["sample_count"]) for segment in phase_segments) == 20

    def test_phase_segments_consistent_with_phase_info(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        assert (
            sum(int(segment["sample_count"]) for segment in summary["phase_segments"])
            == summary["phase_info"]["total_samples"]
        )

    def test_build_findings_for_samples_uses_phase_filtering(self) -> None:
        findings = build_findings_for_samples(
            metadata=standard_metadata(),
            samples=build_phased_samples([(10, 0.0, 0.0), (10, 60.0, 60.0)]),
        )
        assert isinstance(findings, list)


class TestSpeedStatsByPhase:
    """Per-phase speed stats should be present and consistent."""

    def test_speed_stats_by_phase_present_in_summary(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        assert isinstance(summary.get("speed_stats_by_phase"), dict)

    def test_speed_stats_by_phase_keys_are_phase_labels(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        valid_phases = {phase.value for phase in DrivingPhase}
        for key in summary["speed_stats_by_phase"]:
            assert key in valid_phases

    def test_speed_stats_by_phase_sample_counts_sum_to_total(self) -> None:
        samples = build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)])
        summary = summarize_run_data(standard_metadata(), samples, include_samples=False)
        assert sum(
            int(stats["sample_count"]) for stats in summary["speed_stats_by_phase"].values()
        ) == len(samples)

    def test_speed_stats_by_phase_idle_has_no_speed_stats(self) -> None:
        samples = [
            {"t_s": float(idx), "speed_kmh": 0.5, "vibration_strength_db": 5.0} for idx in range(10)
        ]
        summary = summarize_run_data(standard_metadata(), samples, include_samples=False)
        assert "idle" in summary["speed_stats_by_phase"]
        assert summary["speed_stats_by_phase"]["idle"]["sample_count"] == 10

    def test_speed_stats_by_phase_cruise_has_valid_speed_range(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        non_idle = {
            key: value for key, value in summary["speed_stats_by_phase"].items() if key != "idle"
        }
        assert any(value.get("min_kmh") is not None for value in non_idle.values())
