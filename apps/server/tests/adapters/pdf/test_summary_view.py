"""Tests for explicit summary boundary helper functions."""

from __future__ import annotations

from vibesensor.adapters.pdf.mapping import (
    _origin_from_aggregate,
    prepare_report_mapping_context,
)
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
from vibesensor.shared.boundaries.diagnostic_case import (
    test_run_from_summary as _test_run_from_summary,
)
from vibesensor.shared.boundaries.finding import step_payloads_from_plan
from vibesensor.shared.boundaries.vibration_origin import origin_payload_from_finding


def _minimal_summary(**overrides: object) -> dict[str, object]:
    """Build a minimal SummaryData dict with overrides."""
    base: dict = {
        "file_name": "test",
        "run_id": "run-1",
        "rows": 10,
        "duration_s": 5.0,
        "record_length": "0:05",
        "lang": "en",
        "report_date": "2025-01-01T10:00:00Z",
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
    return base


class TestSummaryHelpers:
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
        assert origin is not None
        assert origin.projected_location == "Front Left / Front Right"
        assert origin.alternative_locations == ("front_right",)
        assert origin.dominant_phase == "acceleration"
        assert origin.speed_band == "80-90 km/h"

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
        origin = origin_payload_from_finding(primary)
        assert origin["location"] == "Front Left / Front Right"
        assert origin["alternative_locations"] == ["front_right"]
        assert origin["dominant_phase"] == "acceleration"
        assert origin["speed_band"] == "80-90 km/h"

    def test_sensor_locations_active_prefers_connected(self) -> None:
        ctx = prepare_report_mapping_context(_minimal_summary())
        assert ctx.sensor_locations_active == ["front_left"]

    def test_sensor_locations_active_fallback(self) -> None:
        ctx = prepare_report_mapping_context(
            _minimal_summary(sensor_locations_connected_throughout=[]),
        )
        assert "front_left" in ctx.sensor_locations_active

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

    def test_warnings(self) -> None:
        warns = [{"title": "Low data", "severity": "warn"}]
        s = _minimal_summary(warnings=warns)
        assert len(s["warnings"]) == 1

    def test_sensor_intensity_by_location(self) -> None:
        intensity = [{"location": "front_left", "p95_intensity_db": 25.0}]
        s = _minimal_summary(sensor_intensity_by_location=intensity)
        assert len(s["sensor_intensity_by_location"]) == 1
