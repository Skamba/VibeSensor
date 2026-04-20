"""Tests for explicit summary boundary helper functions."""

from __future__ import annotations

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
from vibesensor.shared.boundaries.analysis_payloads import project_analysis_summary
from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
    test_run_from_summary as _test_run_from_summary,
)
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.reporting.projection import resolve_report_origin
from vibesensor.shared.boundaries.summary_fields.origin import origin_payload_from_finding
from vibesensor.shared.boundaries.summary_fields.test_plan import step_payloads_from_plan


def _minimal_summary(**overrides: object) -> dict[str, object]:
    """Build a minimal SummaryData dict with overrides."""
    base: dict[str, object] = {
        "file_name": "test",
        "run_id": "run-1",
        "rows": 10,
        "duration_s": 5.0,
        "record_length": "0:05",
        "lang": "en",
        "report_date": "2025-01-01T10:00:00Z",
        "metadata": {
            "run_id": "run-1",
            "active_car_snapshot": {"name": "Test Car"},
        },
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
    raw_metadata = base.get("metadata")
    raw_run_id = str(base.get("run_id") or "").strip()
    if isinstance(raw_metadata, dict) and raw_metadata and raw_run_id:
        metadata = dict(raw_metadata)
        metadata.setdefault("run_id", raw_run_id)
        base["metadata"] = metadata
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
        origin = resolve_report_origin(aggregate)
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

    def test_test_run_from_summary_enriches_primary_origin_from_summary_payload(self) -> None:
        summary = _minimal_summary(
            top_causes=[
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "rear left",
                    "strongest_speed_band": "80-90 km/h",
                    "confidence": 0.83,
                }
            ],
            most_likely_origin={
                "location": "rear left / front right",
                "alternative_locations": ["front right"],
                "weak_spatial_separation": True,
                "dominance_ratio": 1.3,
            },
        )
        test_run = _test_run_from_summary(summary)
        primary = test_run.primary_finding
        assert primary is not None
        assert primary.location is not None
        assert primary.origin is not None
        assert primary.origin.projected_location == "Rear Left / Front Right"
        assert primary.origin.has_sufficient_location is True

    def test_project_analysis_summary_uses_domain_enriched_origin(self) -> None:
        summary = _minimal_summary(
            top_causes=[
                {
                    "finding_id": "F001",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "rear left",
                    "strongest_speed_band": "80-90 km/h",
                    "confidence": 0.83,
                }
            ],
            most_likely_origin={
                "location": "rear left / front right",
                "alternative_locations": ["front right"],
                "weak_spatial_separation": True,
            },
        )
        projected, test_run = project_analysis_summary(summary)
        primary = test_run.primary_finding
        assert primary is not None
        assert primary.origin is not None
        assert primary.origin.projected_location == "Rear Left / Front Right"
        assert projected["most_likely_origin"]["location"] == primary.origin.projected_location

    def test_summary_origin_enrichment_skips_other_duplicate_f_peak_findings(self) -> None:
        summary = _minimal_summary(
            findings=[
                {
                    "finding_id": "F_PEAK",
                    "finding_key": "peak_a",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "rear left",
                    "strongest_speed_band": "80-90 km/h",
                    "confidence": 0.83,
                    "frequency_hz": 13.2,
                },
                {
                    "finding_id": "F_PEAK",
                    "finding_key": "peak_b",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "front right",
                    "strongest_speed_band": "80-90 km/h",
                    "confidence": 0.62,
                    "frequency_hz": 26.4,
                },
            ],
            top_causes=[
                {
                    "finding_id": "F_PEAK",
                    "finding_key": "peak_a",
                    "suspected_source": "wheel/tire",
                    "strongest_location": "rear left",
                    "strongest_speed_band": "80-90 km/h",
                    "confidence": 0.83,
                    "frequency_hz": 13.2,
                }
            ],
            most_likely_origin={
                "location": "rear left / front right",
                "alternative_locations": ["front right"],
                "weak_spatial_separation": True,
            },
        )
        test_run = _test_run_from_summary(summary)
        primary = test_run.primary_finding
        assert primary is not None
        assert primary.origin is not None
        assert primary.origin.projected_location == "Rear Left / Front Right"

        findings_by_key = {finding.finding_key: finding for finding in test_run.findings}
        secondary = findings_by_key["peak_b"]
        assert secondary.origin is not None
        assert secondary.origin.has_sufficient_location is False
        assert secondary.origin.projected_location == "Unknown"
        assert secondary.location is None
        assert secondary.strongest_location == "front right"

    def test_sensor_locations_active_prefers_connected(self) -> None:
        prepared = prepare_report_input(_minimal_summary())
        assert prepared.domain_test_run is not None
        assert prepared.report_facts is not None
        assert prepared.report_facts.sensor.active_locations == ("front_left",)

    def test_sensor_locations_active_requires_connected_throughout(self) -> None:
        prepared = prepare_report_input(_minimal_summary(sensor_locations_connected_throughout=[]))
        assert prepared.domain_test_run is not None
        assert prepared.report_facts is not None
        assert prepared.report_facts.sensor.active_locations == ()

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
