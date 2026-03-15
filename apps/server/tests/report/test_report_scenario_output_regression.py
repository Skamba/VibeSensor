"""Report-output-focused scenario regressions for metadata, plots, and references."""

from __future__ import annotations

from typing import Any

from test_support.core import standard_metadata
from test_support.sample_scenarios import build_speed_sweep_samples, make_sample

from vibesensor.analysis import summarize_run_data
from vibesensor.analysis.findings import _reference_missing_finding
from vibesensor.analysis.top_cause_selection import select_top_causes
from vibesensor.analysis_settings import wheel_hz_from_speed_kmh
from vibesensor.boundaries.finding import finding_from_payload
from vibesensor.report.mapping import map_summary


class TestPlotDataKeyFix:
    """Plot payload keys should stay populated when their source tables do."""

    def test_amp_vs_speed_populated(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_samples(n=30, vib_db=20.0),
        )
        amp_points = summary.get("plots", {}).get("amp_vs_speed", [])
        if summary.get("speed_breakdown"):
            assert len(amp_points) > 0


class TestMultiSensorLocalization:
    """Multi-sensor runs should retain strongest-location evidence in summary output."""

    def test_multi_sensor_run(self) -> None:
        samples: list[dict[str, Any]] = []
        tire_circumference = 2.036
        for idx in range(30):
            speed = 40.0 + idx * 2.0
            wheel_hz = wheel_hz_from_speed_kmh(speed, tire_circumference) or 10.0
            samples.append(
                make_sample(
                    t_s=float(idx),
                    speed_kmh=speed,
                    vibration_strength_db=22.0,
                    client_name="Front-Left Wheel",
                    client_id="sensor-A",
                    top_peaks=[{"hz": wheel_hz, "amp": 0.06}],
                    strength_floor_amp_g=0.003,
                ),
            )
            samples.append(
                make_sample(
                    t_s=float(idx) + 0.5,
                    speed_kmh=speed,
                    vibration_strength_db=14.0,
                    client_name="Rear-Right Wheel",
                    client_id="sensor-B",
                    top_peaks=[{"hz": wheel_hz, "amp": 0.02}],
                    strength_floor_amp_g=0.003,
                ),
            )

        summary = summarize_run_data(standard_metadata(), samples, include_samples=False)
        assert len(summary.get("sensor_locations", [])) >= 2
        intensities = summary.get("sensor_intensity_by_location", [])
        if len(intensities) >= 2:
            top_location = intensities[0].get("location")
            assert "Front-Left" in str(top_location) or "front" in str(top_location).lower()


class TestReportMetadataCompleteness:
    """Mapped report data should keep enriched metadata and next-step content."""

    def test_report_data_has_metadata_fields(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_samples(n=20, vib_db=18.0),
            include_samples=False,
        )
        template = map_summary(summary)
        assert template.duration_text is not None
        assert template.sample_count > 0
        assert template.sensor_count >= 1

    def test_next_steps_have_enriched_fields(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_samples(n=40, peak_amp=0.06, vib_db=22.0),
            include_samples=False,
        )
        template = map_summary(summary)
        for step in template.next_steps:
            assert step.action


class TestReferenceFindingDistinguishability:
    """Reference-gap findings must remain distinct from diagnostic findings."""

    def test_reference_finding_has_finding_kind_field(self) -> None:
        reference = _reference_missing_finding(
            finding_id="REF_SPEED",
            suspected_source="unknown",
            evidence_summary="Speed data missing",
            quick_checks=["Check GPS"],
        )
        assert reference.get("finding_kind") == "reference"

    def test_reference_findings_excluded_from_top_causes(self) -> None:
        reference = _reference_missing_finding(
            finding_id="REF_SPEED",
            suspected_source="unknown",
            evidence_summary="Speed data missing",
            quick_checks=[],
        )
        findings = [
            reference,
            {
                "finding_id": "F001",
                "confidence": 0.80,
                "suspected_source": "wheel/tire",
                "severity": "diagnostic",
            },
        ]
        findings_domain = tuple(finding_from_payload(f) for f in findings)
        for cause in select_top_causes(findings_domain):
            assert not str(cause.finding_id or "").startswith("REF_")

    def test_all_ref_variants_have_reference_type(self) -> None:
        for finding_id in ("REF_SPEED", "REF_WHEEL", "REF_ENGINE", "REF_SAMPLE_RATE"):
            reference = _reference_missing_finding(
                finding_id=finding_id,
                suspected_source="unknown",
                evidence_summary="missing",
                quick_checks=[],
            )
            assert reference.get("finding_kind") == "reference"

    def test_reference_finding_confidence_is_none(self) -> None:
        reference = _reference_missing_finding(
            finding_id="REF_SPEED",
            suspected_source="unknown",
            evidence_summary="Speed data missing",
            quick_checks=[],
        )
        assert "confidence" in reference
        assert reference["confidence"] is None
