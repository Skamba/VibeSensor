"""Tests for explicit summary boundary helper functions."""

from __future__ import annotations

from vibesensor.analysis._types import AnalysisSummary
from vibesensor.boundaries.diagnostic_case import (
    test_run_from_summary as _test_run_from_summary,
)
from vibesensor.boundaries.test_steps import step_payloads_from_plan
from vibesensor.boundaries.vibration_origin import origin_payload_from_finding
from vibesensor.domain import (
    Finding,
    LocationHotspot,
    RecommendedAction,
    RunCapture,
    TestRun,
    VibrationOrigin,
)
from vibesensor.domain import (
    TestPlan as DomainTestPlan,
)
from vibesensor.report.mapping import (
    _origin_from_aggregate,
    summary_end_time_utc,
    summary_firmware_version,
    summary_metadata,
    summary_origin,
    summary_raw_sample_rate_hz,
    summary_record_length,
    summary_row_count,
    summary_run_suitability,
    summary_sample_rate_hz_text,
    summary_sensor_count_used,
    summary_sensor_intensity_by_location,
    summary_sensor_locations_active,
    summary_sensor_model,
    summary_speed_stats,
    summary_start_time_utc,
    summary_test_plan,
    summary_warnings,
)


def _minimal_summary(**overrides: object) -> AnalysisSummary:
    """Build a minimal SummaryData dict with overrides."""
    base: dict = {
        "file_name": "test",
        "run_id": "run-1",
        "rows": 10,
        "duration_s": 5.0,
        "record_length": "0:05",
        "lang": "en",
        "metadata": {"car_name": "Test Car"},
        "findings": [],
        "top_causes": [],
        "speed_stats": {
            "min_kmh": 50.0,
            "max_kmh": 100.0,
            "mean_kmh": 75.0,
            "stddev_kmh": 10.0,
            "range_kmh": 50.0,
            "steady_speed": False,
        },
        "most_likely_origin": {
            "location": "front_left",
            "alternative_locations": [],
            "suspected_source": "wheel/tire",
            "dominance_ratio": 2.0,
            "weak_spatial_separation": False,
        },
        "sensor_locations": ["front_left", "front_right"],
        "sensor_locations_connected_throughout": ["front_left"],
        "sensor_count_used": 2,
        "start_time_utc": "2025-01-01T10:00:00Z",
        "end_time_utc": "2025-01-01T10:00:05Z",
        "raw_sample_rate_hz": 100.0,
        "sensor_model": "MPU6050",
        "firmware_version": "1.0.0",
        "run_suitability": [],
        "warnings": [],
        "test_plan": [],
        "sensor_intensity_by_location": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


class TestSummaryHelpers:
    def test_metadata(self) -> None:
        assert summary_metadata(_minimal_summary())["car_name"] == "Test Car"

    def test_row_count(self) -> None:
        assert summary_row_count(_minimal_summary(rows=42)) == 42

    def test_record_length(self) -> None:
        assert summary_record_length(_minimal_summary(record_length="1:30")) == "1:30"

    def test_record_length_none(self) -> None:
        assert summary_record_length(_minimal_summary(record_length=None)) is None

    def test_start_time_utc(self) -> None:
        assert summary_start_time_utc(_minimal_summary()) == "2025-01-01T10:00:00Z"

    def test_end_time_utc(self) -> None:
        assert summary_end_time_utc(_minimal_summary()) == "2025-01-01T10:00:05Z"

    def test_raw_sample_rate_hz(self) -> None:
        assert summary_raw_sample_rate_hz(_minimal_summary(raw_sample_rate_hz=200.0)) == 200.0

    def test_sensor_model(self) -> None:
        assert summary_sensor_model(_minimal_summary()) == "MPU6050"

    def test_firmware_version(self) -> None:
        assert summary_firmware_version(_minimal_summary()) == "1.0.0"

    def test_sensor_count_used(self) -> None:
        assert summary_sensor_count_used(_minimal_summary(sensor_count_used=3)) == 3

    def test_speed_stats(self) -> None:
        assert summary_speed_stats(_minimal_summary())["min_kmh"] == 50.0

    def test_origin(self) -> None:
        assert summary_origin(_minimal_summary())["location"] == "front_left"

    def test_report_origin_projection_reads_domain_vibration_origin(self) -> None:
        primary = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            strongest_location="front_left",
            strongest_speed_band="80-90 km/h",
            dominance_ratio=1.05,
            weak_spatial_separation=True,
            location=LocationHotspot.from_analysis_inputs(
                strongest_location="front_left",
                ambiguous=True,
                alternative_locations=["front_right"],
                dominance_ratio=1.05,
            ),
            origin=VibrationOrigin.from_analysis_inputs(
                suspected_source=Finding(suspected_source="wheel/tire").suspected_source,
                hotspot=LocationHotspot.from_analysis_inputs(
                    strongest_location="front_left",
                    ambiguous=True,
                    alternative_locations=["front_right"],
                    dominance_ratio=1.05,
                ),
                dominance_ratio=1.05,
                speed_band="80-90 km/h",
                dominant_phase="acceleration",
                reason="domain rationale",
            ),
        )
        aggregate = TestRun(
            capture=RunCapture(run_id="run-1"),
            findings=(primary,),
            top_causes=(primary,),
        )
        origin = _origin_from_aggregate(aggregate, _minimal_summary()["most_likely_origin"])
        assert origin["location"] == "Front Left / Front Right"
        assert origin["alternative_locations"] == ["front_right"]
        assert origin["dominant_phase"] == "acceleration"
        assert origin["speed_band"] == "80-90 km/h"

    def test_history_projection_reads_domain_vibration_origin(self) -> None:
        summary = _minimal_summary(
            findings=[
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front_left",
                    "strongest_speed_band": "80-90 km/h",
                    "dominance_ratio": 1.05,
                    "weak_spatial_separation": True,
                    "dominant_phase": "acceleration",
                    "evidence_summary": "payload rationale",
                    "location_hotspot": {
                        "top_location": "front_left",
                        "ambiguous_location": True,
                        "ambiguous_locations": ["front_left", "front_right"],
                    },
                }
            ],
            top_causes=[
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front_left",
                    "strongest_speed_band": "80-90 km/h",
                    "dominance_ratio": 1.05,
                    "weak_spatial_separation": True,
                    "dominant_phase": "acceleration",
                    "evidence_summary": "payload rationale",
                    "location_hotspot": {
                        "top_location": "front_left",
                        "ambiguous_location": True,
                        "ambiguous_locations": ["front_left", "front_right"],
                    },
                }
            ],
            most_likely_origin={},
        )
        test_run = _test_run_from_summary(summary)
        primary = test_run.primary_finding
        assert primary is not None
        origin = origin_payload_from_finding(primary, {})
        assert origin["location"] == "Front Left / Front Right"
        assert origin["alternative_locations"] == ["front_right"]
        assert origin["dominant_phase"] == "acceleration"
        assert origin["speed_band"] == "80-90 km/h"

    def test_sensor_locations_active_prefers_connected(self) -> None:
        assert summary_sensor_locations_active(_minimal_summary()) == ["front_left"]

    def test_sensor_locations_active_fallback(self) -> None:
        assert "front_left" in summary_sensor_locations_active(
            _minimal_summary(sensor_locations_connected_throughout=[])
        )

    def test_sample_rate_hz_text(self) -> None:
        assert summary_sample_rate_hz_text(_minimal_summary(raw_sample_rate_hz=100.0)) == "100"

    def test_sample_rate_hz_text_none(self) -> None:
        assert summary_sample_rate_hz_text(_minimal_summary(raw_sample_rate_hz=None)) is None

    def test_test_plan(self) -> None:
        plan = [{"what": "test something", "why": "to verify"}]
        assert len(summary_test_plan(_minimal_summary(test_plan=plan))) == 1

    def test_boundary_test_plan_payload_projects_semantic_action_fields(self) -> None:
        projected = step_payloads_from_plan(
            DomainTestPlan(
                actions=(
                    RecommendedAction(
                        action_id=" wheel_balance_and_runout ".strip(),
                        what="  ACTION_WHEEL_BALANCE_WHAT  ",
                        why="   ",
                        confirm=" vibration drops ",
                        falsify="  no change  ",
                        eta=" 10-20 min ",
                        priority=2,
                    ),
                    RecommendedAction(
                        action_id="wheel_tire_condition",
                        what="ACTION_TIRE_CONDITION_WHAT",
                        why="ACTION_TIRE_CONDITION_WHY",
                        priority=1,
                    ),
                )
            )
        )

        assert projected == [
            {
                "action_id": "wheel_tire_condition",
                "what": "ACTION_TIRE_CONDITION_WHAT",
                "why": "ACTION_TIRE_CONDITION_WHY",
                "confirm": None,
                "falsify": None,
                "eta": None,
            },
            {
                "action_id": "wheel_balance_and_runout",
                "what": "ACTION_WHEEL_BALANCE_WHAT",
                "why": None,
                "confirm": "vibration drops",
                "falsify": "no change",
                "eta": "10-20 min",
            },
        ]

    def test_history_projection_uses_canonical_test_plan_payload(self) -> None:
        summary = _minimal_summary(
            findings=[{"finding_id": "F001", "suspected_source": "engine"}],
            top_causes=[{"finding_id": "F001", "suspected_source": "engine"}],
            test_plan=[
                {
                    "action_id": "engine_mounts_and_accessories",
                    "what": "  ACTION_ENGINE_MOUNTS_WHAT  ",
                    "why": "   ",
                    "confirm": " movement changes ",
                    "falsify": " no change ",
                    "eta": " 15-30 min ",
                }
            ],
        )

        test_run = _test_run_from_summary(summary)
        projected_plan = step_payloads_from_plan(test_run.test_plan)

        assert projected_plan == [
            {
                "action_id": "engine_mounts_and_accessories",
                "what": "ACTION_ENGINE_MOUNTS_WHAT",
                "why": None,
                "confirm": "movement changes",
                "falsify": "no change",
                "eta": "15-30 min",
            }
        ]

    def test_run_suitability(self) -> None:
        checks = [{"check": "SPEED", "state": "pass", "explanation": "ok"}]
        assert len(summary_run_suitability(_minimal_summary(run_suitability=checks))) == 1

    def test_warnings(self) -> None:
        warns = [{"title": "Low data", "severity": "warn"}]
        assert len(summary_warnings(_minimal_summary(warnings=warns))) == 1

    def test_sensor_intensity_by_location(self) -> None:
        intensity = [{"location": "front_left", "p95_intensity_db": 25.0}]
        assert (
            len(
                summary_sensor_intensity_by_location(
                    _minimal_summary(sensor_intensity_by_location=intensity)
                )
            )
            == 1
        )
