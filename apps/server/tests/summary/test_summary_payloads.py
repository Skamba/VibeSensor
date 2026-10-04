"""Analysis summary payloads: built, stored, reloaded and projected for history intact."""

from __future__ import annotations

import pytest
from test_support.findings import NO_FAULT_DIAGNOSIS, make_finding_payload

from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.driving_segment import DrivingPhase, DrivingPhaseInterval
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_evidence import FindingEvidence
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.location_hotspot import LocationIntensitySummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.history.projection import (
    project_analysis_summary,
)
from vibesensor.summary.analysis_metadata import report_analysis_metadata_from_mapping
from vibesensor.summary.builder import build_analysis_summary
from vibesensor.summary.fallback_reasons import derive_report_fallback_reasons
from vibesensor.summary.finding_fields import (
    finding_from_payload,
    finding_payload_from_domain,
)
from vibesensor.summary.reconstruction import (
    test_run_from_summary as _test_run_from_summary,
)
from vibesensor.summary.run_context_warning import (
    WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
    RunContextWarning,
    normalize_run_context_warnings,
)
from vibesensor.summary.test_plan_fields import step_payloads_from_plan


def test_build_analysis_summary_exposes_stable_public_entrypoint() -> None:
    summary = build_analysis_summary(
        file_name="run.csv",
        run_id="run-1",
        samples=[{"t_s": 0.0, "speed_kmh": 32.0, "vibration_strength_db": 14.0}],
        duration_s=12.5,
        language="en",
        metadata={"end_time_utc": "2026-01-01T00:00:00Z"},
        raw_sample_rate_hz=100.0,
        speed_breakdown=[],
        phase_speed_breakdown=[],
        phase_segments=[],
        run_noise_baseline_g=0.02,
        speed_breakdown_skipped_reason=None,
        findings=(),
        top_causes=(),
        most_likely_origin=None,
        test_plan=[],
        phase_timeline=[
            DrivingPhaseInterval(
                phase=DrivingPhase.CRUISE,
                start_t_s=0.0,
                end_t_s=12.5,
            )
        ],
        speed_stats=SpeedProfileSummary(mean_kmh=32.0, sample_count=1),
        speed_stats_by_phase={},
        phase_info=DrivingPhaseSummary(has_cruise=True, cruise_pct=100.0),
        sensor_locations=["front"],
        connected_locations={"front"},
        sensor_intensity_by_location=[
            LocationIntensitySummary(location="front", p95_intensity_db=18.0)
        ],
        run_suitability=None,
        speed_values=[32.0],
        speed_non_null_pct=100.0,
        accel_stats={
            "x_mean": 0.0,
            "x_var": 0.1,
            "y_mean": 0.0,
            "y_var": 0.1,
            "z_mean": 1.0,
            "z_var": 0.2,
            "sensor_limit": 2.0,
        },
        amp_metric_values=[14.0],
        diagnosis=NO_FAULT_DIAGNOSIS,
    )

    assert summary["run_id"] == "run-1"
    assert summary["rows"] == 1
    assert summary["sensor_count_used"] == 1
    assert summary["warnings"] == []
    assert summary["data_quality"]["speed_coverage"]["count_non_null"] == 1


def test_projection_keeps_strength_metric_when_evidence_exists_without_nested_strength() -> None:
    payload = finding_payload_from_domain(
        Finding(
            finding_id="F001",
            suspected_source=VibrationSource.WHEEL_TIRE,
            vibration_strength_db=22.3,
            evidence=FindingEvidence(
                match_rate=0.8,
                presence_ratio=0.9,
                burstiness=0.1,
                spatial_concentration=0.7,
                frequency_correlation=0.6,
                speed_uniformity=0.5,
                spatial_uniformity=0.4,
                snr_db=15.0,
            ),
        )
    )

    assert payload["amplitude_metric"]["value"] == 22.3
    assert payload["evidence_metrics"]["vibration_strength_db"] == 22.3


def _roundtrip(finding: Finding) -> Finding:
    """Serialize then deserialize a Finding."""
    payload = finding_payload_from_domain(finding)
    return finding_from_payload(payload)


class TestFindingRoundtrip:
    """Finding → FindingPayload → Finding preserves domain-relevant fields."""

    def test_scalar_fields_preserved(self) -> None:
        original = Finding(
            finding_id="F002",
            finding_key="peak_200hz",
            suspected_source=VibrationSource.DRIVELINE,
            confidence=0.85,
            frequency_hz=200.0,
            order="2x driveshaft",
            severity="diagnostic",
            strongest_location="rear-left",
            strongest_speed_band="80-100 km/h",
            peak_classification="harmonic",
            ranking_score=3.5,
            dominance_ratio=2.1,
            diffuse_excitation=True,
            weak_spatial_separation=True,
            vibration_strength_db=22.3,
            cruise_fraction=0.6,
        )
        restored = _roundtrip(original)
        assert restored.finding_id == original.finding_id
        assert restored.finding_key == original.finding_key
        assert restored.suspected_source is original.suspected_source
        assert restored.confidence == pytest.approx(original.confidence)
        assert restored.frequency_hz == pytest.approx(original.frequency_hz)
        assert restored.order == original.order
        assert restored.severity == original.severity
        assert restored.strongest_location == original.strongest_location
        assert restored.strongest_speed_band == original.strongest_speed_band
        assert restored.peaks.classification == original.peaks.classification
        assert restored.ranking_score == pytest.approx(original.ranking_score)
        assert restored.dominance_ratio == pytest.approx(original.dominance_ratio)
        assert restored.diffuse_excitation is True
        assert restored.weak_spatial_separation is True
        assert restored.vibration_strength_db == pytest.approx(original.vibration_strength_db)
        assert restored.cruise_fraction == pytest.approx(original.cruise_fraction)


_REFERENCE_CONTEXT_WARNING = RunContextWarning(
    code=WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
    severity="warn",
    applies_to="order_analysis",
    title={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
    detail={"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
)


def test_normalize_run_context_warnings_keeps_wire_payload_shape() -> None:
    warnings = normalize_run_context_warnings(
        [
            {
                "code": WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
                "severity": "warn",
                "applies_to": "order_analysis",
                "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
                "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
            },
            "skip-me",
        ]
    )

    assert warnings == [_REFERENCE_CONTEXT_WARNING]


def _canonical_metadata() -> dict[str, object]:
    return {
        "active_car_snapshot": {
            "name": "Guard Car",
            "type": "sedan",
        }
    }


def test_project_analysis_summary_projects_run_suitability_from_reconstructed_test_run() -> None:
    summary = {
        "case_id": "case-001",
        "run_id": "run-001",
        "metadata": _canonical_metadata(),
        "findings": [make_finding_payload(finding_id="F001", confidence=0.8)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.8)],
        "test_plan": [
            {
                "action_id": "check-wheel",
                "what": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT"},
                "why": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHY"},
            }
        ],
        "run_suitability": [
            {"check_key": "speed_profile", "state": "warn"},
        ],
    }

    projected, test_run = project_analysis_summary(summary)

    assert test_run.suitability is not None
    assert projected["run_suitability"] == [
        {
            "check_key": "speed_profile",
            "state": "warn",
            "explanation": test_run.suitability.checks[0].explanation_i18n_ref(),
        }
    ]


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


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"raw_capture_loss_policy_severity": "fatal", "raw_backed_sample_count": 10},
            ("raw_capture_loss_exceeded",),
        ),
        (
            {"raw_capture_available": False, "raw_capture_mode": "summary_only"},
            ("raw_capture_not_configured", "legacy_summary_only"),
        ),
        (
            {"raw_capture_finalize_status": "failed", "raw_capture_mode": "raw_backed"},
            ("raw_capture_finalize_failed",),
        ),
        ({"raw_capture_mode": "raw_backed", "raw_backed_sample_count": 10}, ()),
    ],
    ids=["fatal-loss", "no-raw-capture", "finalize-failed", "raw-backed"],
)
def test_report_says_why_raw_evidence_was_not_used(
    metadata: dict[str, object], expected: tuple[str, ...]
) -> None:
    reasons = derive_report_fallback_reasons(report_analysis_metadata_from_mapping(metadata))
    assert reasons == expected
