"""Report-output-focused scenario regressions for metadata and references."""

from __future__ import annotations

import pytest
from test_support.core import standard_metadata
from test_support.findings import make_ref_finding
from test_support.sample_scenarios import build_speed_sweep_samples, make_sample

from vibesensor.analysis.summarize import summarize_run_data
from vibesensor.analysis.top_cause_selection import select_top_causes
from vibesensor.common.units import KMH_TO_MPS
from vibesensor.report.document.builder import build_report_document
from vibesensor.report.preparation import prepare_report_input
from vibesensor.summary.finding_fields import finding_from_payload


class TestMultiSensorLocalization:
    """Multi-sensor runs should retain strongest-location evidence in summary output."""

    def test_multi_sensor_run(self) -> None:
        samples: list[dict[str, object]] = []
        tire_circumference = 2.036
        for idx in range(30):
            speed = 40.0 + idx * 2.0
            wheel_hz = speed * KMH_TO_MPS / tire_circumference
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
        assert summary.get("sensor_locations") == ["Front-Left Wheel", "Rear-Right Wheel"]

        intensities = summary["sensor_intensity_by_location"]
        assert [row["location"] for row in intensities] == ["Front-Left Wheel", "Rear-Right Wheel"]
        assert [row["sample_count"] for row in intensities] == [30, 30]

        diagnostic_findings = [
            finding
            for finding in summary["findings"]
            if not str(finding.get("finding_id", "")).startswith("REF_")
        ]
        assert len(diagnostic_findings) == 1
        finding = diagnostic_findings[0]
        assert finding["suspected_source"] == "wheel/tire"
        assert finding["confidence_label_key"] == "CONFIDENCE_HIGH"
        assert finding["strongest_location"] == "Front-Left Wheel"
        assert finding["strongest_speed_band"] == "40-50 km/h"
        assert finding["dominance_ratio"] == pytest.approx(3.0)


class TestReportMetadataCompleteness:
    """Mapped report data should keep enriched metadata and next-step content."""

    def test_report_data_has_metadata_fields(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_samples(n=20, vib_db=18.0),
            include_samples=False,
        )
        template = build_report_document(prepare_report_input(summary))
        assert template.duration_text == "00:19.0"
        assert template.sample_count == 20
        assert template.sensor_count == 1

    def test_next_steps_have_enriched_fields(self) -> None:
        summary = summarize_run_data(
            standard_metadata(),
            build_speed_sweep_samples(n=40, peak_amp=0.06, vib_db=22.0),
            include_samples=False,
        )
        template = build_report_document(prepare_report_input(summary))
        assert [step.action for step in template.next_steps] == [
            (
                "Add sensor locations (e.g. near each wheel, engine bay) "
                "to improve spatial separation."
            ),
            (
                "Ensure tire size, engine RPM, and speed references are complete "
                "for accurate order matching."
            ),
        ]


class TestReferenceFindingDistinguishability:
    """Reference-gap findings must remain distinct from diagnostic findings."""

    def test_reference_finding_has_finding_kind_field(self) -> None:
        reference = finding_from_payload(make_ref_finding("REF_SPEED"))
        assert reference.kind is not None
        assert reference.kind.value == "reference"

    def test_reference_findings_excluded_from_top_causes(self) -> None:
        reference = finding_from_payload(make_ref_finding("REF_SPEED"))
        findings = [
            reference,
            finding_from_payload(
                {
                    "finding_id": "F001",
                    "confidence": 0.80,
                    "suspected_source": "wheel/tire",
                    "severity": "diagnostic",
                }
            ),
        ]
        for cause in select_top_causes(tuple(findings)):
            assert not str(cause.finding_id or "").startswith("REF_")

    def test_all_ref_variants_have_reference_type(self) -> None:
        for finding_id in ("REF_SPEED", "REF_WHEEL", "REF_ENGINE", "REF_SAMPLE_RATE"):
            reference = finding_from_payload(make_ref_finding(finding_id))
            assert reference.kind is not None
            assert reference.kind.value == "reference"

    def test_reference_finding_confidence_is_none(self) -> None:
        reference = finding_from_payload(make_ref_finding("REF_SPEED"))
        assert reference.confidence is None
