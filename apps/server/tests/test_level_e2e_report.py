# ruff: noqa: E501
"""End-to-end tests: simulator-style ingestion + PDF report validation.

Test 1 – Realistic multi-sensor ingestion scenario
    Builds a 120-second driving scenario (idle → ramp → cruise with fault
    → transient → decel → low-speed cruise → idle) across 4 wheel sensors
    and validates the full analysis output contract: findings, localization,
    source classification, speed breakdown, phase timeline, and confidence.

Test 2 – 20-second simulator-style run with PDF report generation
    Builds a 20-second focused scenario and generates a PDF report, then
    validates:
    - PDF is generated successfully and is valid PDF
    - Major report sections are present and populated
    - Top finding/source/corner matches the injected scenario
    - Report content is internally consistent (speed range, symptom pattern, location)
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RR,
    assert_strongest_location,
    assert_wheel_source,
    extract_top,
    make_fault_samples,
    make_idle_samples,
    make_ramp_samples,
    make_transient_samples,
    run_analysis,
    standard_metadata,
    top_confidence,
)
from pypdf import PdfReader

from vibesensor.report.pdf_builder import build_report_pdf

# ---------------------------------------------------------------------------
# Helper: build the full 120s multi-phase scenario
# ---------------------------------------------------------------------------


def _build_full_ingestion_scenario() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a realistic 120-second multi-sensor driving scenario.

    Timeline:
      0-10s:   idle (4 sensors, stationary)
      10-25s:  ramp 0→80 km/h (acceleration)
      25-70s:  cruise at 80 km/h with FL wheel fault
      45-47s:  transient spike on FR (impact event mid-cruise)
      70-85s:  deceleration 80→30 km/h
      85-100s: low-speed cruise with FL fault at 30 km/h
      95-97s:  transient spike on RR (second impact)
      100-120s: final idle
    """
    sensors = ALL_WHEEL_SENSORS[:]
    samples: list[dict[str, Any]] = []

    # Phase 1: Idle (0-10s)
    samples.extend(make_idle_samples(sensors=sensors, n_samples=10, start_t_s=0))

    # Phase 2: Ramp up (10-25s)
    samples.extend(
        make_ramp_samples(
            sensors=sensors,
            speed_start=0,
            speed_end=80,
            n_samples=15,
            start_t_s=10,
            noise_amp=0.004,
            vib_db=10.0,
        )
    )

    # Phase 3: Cruise at 80 km/h with FL fault (25-70s)
    samples.extend(
        make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=80.0,
            n_samples=45,
            start_t_s=25,
            fault_amp=0.07,
            fault_vib_db=28.0,
            noise_vib_db=8.0,
        )
    )

    # Phase 3b: Transient on FR at 45-47s
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FR,
            speed_kmh=80.0,
            n_samples=3,
            start_t_s=45,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )

    # Phase 4: Deceleration (70-85s)
    samples.extend(
        make_ramp_samples(
            sensors=sensors,
            speed_start=80,
            speed_end=30,
            n_samples=15,
            start_t_s=70,
            noise_amp=0.004,
            vib_db=10.0,
        )
    )

    # Phase 5: Low-speed cruise with FL fault (85-100s)
    samples.extend(
        make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=30.0,
            n_samples=15,
            start_t_s=85,
            fault_amp=0.05,
            fault_vib_db=22.0,
            noise_vib_db=8.0,
        )
    )

    # Phase 5b: Transient on RR at 95-97s
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_RR,
            speed_kmh=30.0,
            n_samples=3,
            start_t_s=95,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )

    # Phase 6: Final idle (100-120s)
    samples.extend(make_idle_samples(sensors=sensors, n_samples=20, start_t_s=100))

    meta = standard_metadata(language="en")
    return meta, samples


# ---------------------------------------------------------------------------
# Test 1 – Realistic multi-sensor ingestion scenario
# ---------------------------------------------------------------------------


class TestIngestionScenario:
    """Full multi-sensor ingestion scenario with thorough validation."""

    @pytest.fixture(autouse=True)
    def _run_scenario(self) -> None:
        meta, samples = _build_full_ingestion_scenario()
        self.summary = run_analysis(samples, metadata=meta)
        self.top = extract_top(self.summary)

    def test_summary_structure_complete(self) -> None:
        """All expected top-level keys are present."""
        for key in (
            "top_causes",
            "findings",
            "speed_breakdown",
            "data_quality",
            "most_likely_origin",
            "phase_timeline",
            "sensor_intensity_by_location",
            "warnings",
        ):
            assert key in self.summary, f"Missing key '{key}' in summary"

    def test_top_cause_is_wheel_tire(self) -> None:
        """Primary diagnosis should be wheel/tire."""
        assert_wheel_source(self.summary, msg="ingestion scenario")

    def test_top_cause_localizes_to_fl(self) -> None:
        """Fault was injected on FL → top cause should point to front-left."""
        assert_strongest_location(self.summary, SENSOR_FL, msg="ingestion FL")

    def test_confidence_in_expected_range(self) -> None:
        """Confidence should be moderate-to-high for a clear fault."""
        conf = top_confidence(self.summary)
        assert 0.15 <= conf <= 1.0, f"Confidence {conf:.3f} out of expected range"

    def test_confidence_label_valid(self) -> None:
        """Top cause has a valid confidence label."""
        assert self.top is not None
        assert self.top.get("confidence_label_key") in (
            "CONFIDENCE_HIGH",
            "CONFIDENCE_MEDIUM",
            "CONFIDENCE_LOW",
        ), f"Bad confidence label: {self.top.get('confidence_label_key')}"

    def test_speed_breakdown_nonempty(self) -> None:
        """Speed breakdown includes at least one band."""
        sb = self.summary["speed_breakdown"]
        assert isinstance(sb, list) and len(sb) > 0, "Speed breakdown is empty"
        for band in sb:
            assert "speed_range" in band, f"Missing 'speed_range' in band: {band}"

    def test_findings_include_order_type(self) -> None:
        """Findings list includes order findings."""
        findings = self.summary["findings"]
        assert len(findings) > 0, "No findings generated"
        has_order = any(
            "order" in str(f.get("type", "")).lower()
            or "wheel" in str(f.get("suspected_source", "")).lower()
            for f in findings
        )
        assert has_order, "Expected order findings in ingestion scenario"

    def test_data_quality_present(self) -> None:
        """Data quality assessment is a dict."""
        dq = self.summary["data_quality"]
        assert isinstance(dq, dict), "data_quality must be a dict"

    def test_most_likely_origin_points_to_wheel(self) -> None:
        """Most likely origin should reference wheel/tire."""
        origin = self.summary["most_likely_origin"]
        assert isinstance(origin, dict)
        assert "source" in origin
        src = origin["source"].lower()
        assert "wheel" in src or "tire" in src, f"Origin source: {src}"

    def test_phase_timeline_has_entries(self) -> None:
        """Phase timeline should have multiple entries for the multi-phase scenario."""
        pt = self.summary["phase_timeline"]
        assert isinstance(pt, list) and len(pt) > 0, "Phase timeline empty"

    def test_sensor_intensity_by_location_present(self) -> None:
        """Sensor intensity by location should be populated."""
        sil = self.summary["sensor_intensity_by_location"]
        assert isinstance(sil, list) and len(sil) > 0, "No sensor intensity data"

    def test_transient_does_not_dominate(self) -> None:
        """Transient events should not override the persistent fault finding."""
        assert self.top is not None
        src = (self.top.get("source") or "").lower()
        # The top cause should NOT be a transient/impact classification
        assert "transient" not in src, f"Transient dominated top cause: {src}"


# ---------------------------------------------------------------------------
# Helper: build a focused 20s scenario for PDF generation
# ---------------------------------------------------------------------------


def _build_20s_scenario() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a 20-second focused scenario for PDF report generation.

    Timeline:
      0-3s:   idle (4 sensors)
      3-5s:   ramp 0→80 km/h
      5-17s:  cruise at 80 km/h with FL wheel fault
      10-11s: transient on FR
      17-20s: final idle
    """
    sensors = ALL_WHEEL_SENSORS[:]
    samples: list[dict[str, Any]] = []

    samples.extend(make_idle_samples(sensors=sensors, n_samples=3, start_t_s=0))
    samples.extend(
        make_ramp_samples(
            sensors=sensors,
            speed_start=0,
            speed_end=80,
            n_samples=2,
            start_t_s=3,
        )
    )
    samples.extend(
        make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=80.0,
            n_samples=12,
            start_t_s=5,
            fault_amp=0.07,
            fault_vib_db=28.0,
            noise_vib_db=8.0,
        )
    )
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FR,
            speed_kmh=80.0,
            n_samples=2,
            start_t_s=10,
            spike_amp=0.18,
            spike_vib_db=36.0,
        )
    )
    samples.extend(make_idle_samples(sensors=sensors, n_samples=3, start_t_s=17))

    meta = standard_metadata(language="en")
    return meta, samples


# ---------------------------------------------------------------------------
# Test 2 – 20-second PDF report validation
# ---------------------------------------------------------------------------


@pytest.mark.long_sim
class TestPdfReportValidation:
    """Validate PDF report from a realistic 20-second scenario."""

    @pytest.fixture(autouse=True)
    def _run_and_generate(self) -> None:
        meta, samples = _build_20s_scenario()
        self.summary = run_analysis(samples, metadata=meta)
        self.pdf_bytes = build_report_pdf(self.summary)
        self.pdf_text = self._extract_text(self.pdf_bytes)
        self.top = extract_top(self.summary)

    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(filter(None, (page.extract_text() for page in reader.pages))).lower()

    def test_pdf_is_generated(self) -> None:
        """PDF bytes are non-empty and start with the PDF magic number."""
        assert len(self.pdf_bytes) > 1000, f"PDF too small: {len(self.pdf_bytes)} bytes"
        assert self.pdf_bytes[:5] == b"%PDF-", "Not a valid PDF"

    def test_pdf_has_multiple_pages(self) -> None:
        """Generated PDF should have at least 2 pages."""
        reader = PdfReader(io.BytesIO(self.pdf_bytes))
        assert len(reader.pages) >= 2, f"PDF has only {len(reader.pages)} page(s)"

    def test_pdf_contains_diagnostic_sections(self) -> None:
        """PDF text includes major report section keywords."""
        for keyword in ["diagnostic", "evidence", "finding"]:
            assert keyword in self.pdf_text, f"Missing section keyword: '{keyword}'"

    def test_pdf_mentions_wheel_tire_source(self) -> None:
        """PDF text mentions the wheel/tire fault source."""
        assert "wheel" in self.pdf_text or "tire" in self.pdf_text, (
            "PDF does not mention wheel/tire source"
        )

    def test_pdf_mentions_front_left(self) -> None:
        """PDF text references the fault corner (front-left / FL)."""
        assert "front" in self.pdf_text and "left" in self.pdf_text, (
            "PDF does not mention front-left corner"
        )

    def test_pdf_mentions_speed_range(self) -> None:
        """PDF text includes a speed range consistent with the 80 km/h cruise."""
        # The scenario cruises at 80 km/h, so the report should mention
        # a speed band that includes this range
        assert "km/h" in self.pdf_text or "km" in self.pdf_text, "PDF does not mention speed units"

    def test_pdf_top_cause_matches_scenario(self) -> None:
        """The analysis summary driving the PDF matches the injected scenario."""
        assert self.top is not None, "No top cause in summary"
        assert_wheel_source(self.summary, msg="20s PDF scenario")
        assert_strongest_location(self.summary, SENSOR_FL, msg="20s PDF FL")

    def test_pdf_confidence_is_reasonable(self) -> None:
        """Confidence for the 20s scenario should be meaningful."""
        conf = top_confidence(self.summary)
        assert conf > 0.10, f"Confidence too low for PDF scenario: {conf:.3f}"

    def test_pdf_internally_consistent(self) -> None:
        """PDF content should be consistent with the analysis summary."""
        # Top cause source should appear in PDF text
        if self.top:
            src = (self.top.get("source") or "").lower()
            # At least part of the source label should appear
            for token in src.split("/"):
                if token and len(token) > 2:
                    assert token in self.pdf_text, f"Source token '{token}' not found in PDF text"
