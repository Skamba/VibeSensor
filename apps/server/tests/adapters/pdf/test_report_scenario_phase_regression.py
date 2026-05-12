"""Phase- and timeline-focused scenario regression tests for reporting."""

from __future__ import annotations

import pytest
from test_support.core import standard_metadata
from test_support.sample_scenarios import (
    build_phased_samples,
    build_speed_sweep_samples,
    max_order_source_conf,
)

from vibesensor.adapters.analysis_summary import build_findings_for_samples, summarize_run_data
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    phase_summary,
    segment_run_phases,
)


class TestPhaseSegmentation:
    """Verify driving-phase classification across various speed profiles."""

    def test_idle_to_speed_up(self) -> None:
        samples = build_phased_samples([(5, 0.0, 0.0), (10, 8.0, 80.0), (10, 80.0, 81.0)])

        per_sample, segments = segment_run_phases(sensor_frames_from_mappings(samples))
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
            ],
        )
        per_sample, _segments = segment_run_phases(sensor_frames_from_mappings(samples))
        idle_count = sum(1 for phase in per_sample if phase == DrivingPhase.IDLE)
        assert idle_count >= 6

    def test_coast_down(self) -> None:
        samples = build_phased_samples([(20, 50.0, 2.0)])
        per_sample, _segments = segment_run_phases(sensor_frames_from_mappings(samples))
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
        kwargs: dict[str, object],
        expected: list[bool],
    ) -> None:
        assert diagnostic_sample_mask(phases, **kwargs) == expected

    def test_phase_summary_structure(self) -> None:
        samples = [
            {"t_s": 0.0, "speed_kmh": 0.0},
            {"t_s": 1.0, "speed_kmh": 60.0},
            {"t_s": 2.0, "speed_kmh": 60.0},
        ]
        _, segments = segment_run_phases(sensor_frames_from_mappings(samples))
        info = phase_summary(segments)
        assert info.phase_counts is not None
        assert info.total_samples == 3
        assert abs(sum(info.phase_pcts.values()) - 100.0) < 0.01

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

        per_sample, segments = segment_run_phases(sensor_frames_from_mappings(samples))
        assert len(per_sample) == len(samples)
        phases_found = {segment.phase for segment in segments}
        assert DrivingPhase.IDLE in phases_found
        assert DrivingPhase.ACCELERATION in phases_found
        assert DrivingPhase.CRUISE in phases_found
        assert DrivingPhase.DECELERATION in phases_found or DrivingPhase.COAST_DOWN in phases_found

        info = phase_summary(segments)
        assert info.has_cruise
        assert info.has_acceleration
        assert info.total_samples == len(samples)

    def test_empty_samples_returns_empty(self) -> None:
        per_sample, segments = segment_run_phases([])
        assert per_sample == []
        assert segments == []

    def test_none_speed_treated_as_speed_unknown(self) -> None:
        samples = [{"t_s": 0.0, "speed_kmh": None}, {"t_s": 1.0, "speed_kmh": None}]
        per_sample, _segments = segment_run_phases(sensor_frames_from_mappings(samples))
        assert all(phase == DrivingPhase.SPEED_UNKNOWN for phase in per_sample)


class TestSensorIntensityPhaseContext:
    """Per-location intensity rows should carry phase context in the public summary."""

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
        per_sample_phases, _ = segment_run_phases(sensor_frames_from_mappings(samples))

        idle_count = sum(1 for phase in per_sample_phases if phase == DrivingPhase.IDLE)
        non_idle_count = sum(1 for phase in per_sample_phases if phase != DrivingPhase.IDLE)
        assert idle_count >= 3
        assert non_idle_count >= 5

    def test_build_findings_falls_back_if_too_few_diagnostic_samples(self) -> None:
        samples = [
            {"t_s": float(idx), "speed_kmh": 0.0, "vibration_strength_db": 5.0} for idx in range(10)
        ]
        summary = summarize_run_data(standard_metadata(), samples, include_samples=False)
        assert [
            (finding["finding_id"], finding["finding_kind"], finding["suspected_source"])
            for finding in summary["findings"]
        ] == [
            ("REF_SPEED", "reference", "unknown"),
            ("REF_ENGINE", "reference", "engine"),
        ]
        assert max_order_source_conf(summary) == 0.0
        assert summary["phase_info"] == {
            "phase_counts": {"idle": 10},
            "phase_pcts": {"idle": 100.0},
            "total_samples": 10,
            "segment_count": 1,
            "has_cruise": False,
            "has_acceleration": False,
            "cruise_pct": 0.0,
            "idle_pct": 100.0,
            "speed_unknown_pct": 0.0,
        }

    def test_phase_filtering_does_not_break_full_pipeline(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (20, 10.0, 80.0)]),
            include_samples=False,
        )
        assert summary["findings"] == []
        assert summary["phase_info"]["phase_counts"] == {"idle": 5, "acceleration": 20}
        assert summary["phase_info"]["has_acceleration"] is True
        assert summary["phase_info"]["has_cruise"] is False
        assert summary["phase_speed_breakdown"] == [
            {
                "phase": "idle",
                "count": 5,
                "mean_speed_kmh": None,
                "max_speed_kmh": None,
                "mean_vibration_strength_db": 15.0,
                "max_vibration_strength_db": 15.0,
            },
            {
                "phase": "acceleration",
                "count": 20,
                "mean_speed_kmh": 45.0,
                "max_speed_kmh": 80.0,
                "mean_vibration_strength_db": 15.0,
                "max_vibration_strength_db": 15.0,
            },
        ]


class TestPhaseSpeedBreakdown:
    """Phase-speed breakdown should expose temporal context in the public summary."""

    def test_phase_speed_breakdown_included_in_summary(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        assert summary["phase_speed_breakdown"] == [
            {
                "phase": "idle",
                "count": 5,
                "mean_speed_kmh": None,
                "max_speed_kmh": None,
                "mean_vibration_strength_db": 15.0,
                "max_vibration_strength_db": 15.0,
            },
            {
                "phase": "acceleration",
                "count": 15,
                "mean_speed_kmh": 45.0,
                "max_speed_kmh": 80.0,
                "mean_vibration_strength_db": 15.0,
                "max_vibration_strength_db": 15.0,
            },
        ]

    def test_amp_vs_phase_in_plots(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        assert summary["plots"]["amp_vs_phase"] == [
            {
                "phase": "idle",
                "count": 5,
                "mean_vib_db": 15.0,
                "max_vib_db": 15.0,
                "mean_speed_kmh": None,
            },
            {
                "phase": "acceleration",
                "count": 15,
                "mean_vib_db": 15.0,
                "max_vib_db": 15.0,
                "mean_speed_kmh": 45.0,
            },
        ]


class TestPhaseInfoInSummary:
    """Summary output should propagate serialized phase information consistently."""

    def test_phase_info_present(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_samples(n=20, vib_db=18.0),
            include_samples=False,
        )
        assert summary["phase_info"] == {
            "phase_counts": {"acceleration": 20},
            "phase_pcts": {"acceleration": 100.0},
            "total_samples": 20,
            "segment_count": 1,
            "has_cruise": False,
            "has_acceleration": True,
            "cruise_pct": 0.0,
            "idle_pct": 0.0,
            "speed_unknown_pct": 0.0,
        }

    def test_phase_info_propagated_to_all_dependents(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        assert summary["phase_info"]["phase_counts"] == {"idle": 5, "acceleration": 15}
        assert summary["phase_info"]["phase_pcts"] == {"idle": 25.0, "acceleration": 75.0}
        assert summary["phase_info"]["total_samples"] == 20

        assert [row["phase"] for row in summary["phase_speed_breakdown"]] == [
            "idle",
            "acceleration",
        ]
        assert sum(int(row["count"]) for row in summary["phase_speed_breakdown"]) == 20

        assert summary["sensor_intensity_by_location"][0]["phase_intensity"] == {
            "idle": {"count": 5, "mean_intensity_db": 15.0, "max_intensity_db": 15.0},
            "acceleration": {"count": 15, "mean_intensity_db": 15.0, "max_intensity_db": 15.0},
        }

    def test_phase_segments_serialized_in_summary(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        assert summary["phase_segments"] == [
            {
                "phase": "idle",
                "start_idx": 0,
                "end_idx": 4,
                "start_t_s": 0.0,
                "end_t_s": 4.0,
                "speed_min_kmh": 0.0,
                "speed_max_kmh": 0.0,
                "sample_count": 5,
            },
            {
                "phase": "acceleration",
                "start_idx": 5,
                "end_idx": 19,
                "start_t_s": 5.0,
                "end_t_s": 19.0,
                "speed_min_kmh": 10.0,
                "speed_max_kmh": 80.0,
                "sample_count": 15,
            },
        ]

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
        assert findings == ()


class TestSpeedStatsByPhase:
    """Per-phase speed stats should be present and consistent."""

    def test_speed_stats_by_phase_present_in_summary(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples([(5, 0.0, 0.0), (15, 10.0, 80.0)]),
            include_samples=False,
        )
        assert summary["speed_stats_by_phase"] == {
            "idle": {
                "min_kmh": None,
                "max_kmh": None,
                "mean_kmh": None,
                "stddev_kmh": None,
                "range_kmh": None,
                "steady_speed": False,
                "sample_count": 5,
            },
            "acceleration": {
                "min_kmh": 10.0,
                "max_kmh": 80.0,
                "mean_kmh": 45.0,
                "stddev_kmh": pytest.approx(22.360679774997898),
                "range_kmh": 70.0,
                "steady_speed": False,
                "sample_count": 15,
            },
        }

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
        assert summary["speed_stats_by_phase"] == {
            "idle": {
                "min_kmh": 0.5,
                "max_kmh": 0.5,
                "mean_kmh": 0.5,
                "stddev_kmh": 0.0,
                "range_kmh": 0.0,
                "steady_speed": True,
                "sample_count": 10,
            },
        }

    def test_speed_stats_by_phase_cruise_has_valid_speed_range(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_phased_samples(
                [(5, 0.0, 0.0), (6, 20.0, 80.0), (12, 72.0, 74.0), (4, 74.0, 30.0)]
            ),
            include_samples=False,
        )
        non_idle = {
            key: value for key, value in summary["speed_stats_by_phase"].items() if key != "idle"
        }
        assert non_idle == {
            "acceleration": {
                "min_kmh": 20.0,
                "max_kmh": 80.0,
                "mean_kmh": 50.0,
                "stddev_kmh": pytest.approx(22.44994432064365),
                "range_kmh": 60.0,
                "steady_speed": False,
                "sample_count": 6,
            },
            "cruise": {
                "min_kmh": pytest.approx(72.18181818181819),
                "max_kmh": 74.0,
                "mean_kmh": pytest.approx(73.0909090909091),
                "stddev_kmh": pytest.approx(0.6030226891555259),
                "range_kmh": pytest.approx(1.818181818181813),
                "steady_speed": True,
                "sample_count": 11,
            },
            "deceleration": {
                "min_kmh": 30.0,
                "max_kmh": 74.0,
                "mean_kmh": 56.0,
                "stddev_kmh": pytest.approx(18.6785676348292),
                "range_kmh": 44.0,
                "steady_speed": False,
                "sample_count": 5,
            },
        }
