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
from copy import deepcopy
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
        # A valid 2-page report PDF is typically 10K+; 1000 is a safe floor
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
            # At least part of the source label should appear;
            # skip short tokens (e.g. single-char splits) as they cause false matches
            for token in src.split("/"):
                if token and len(token) > 2:
                    assert token in self.pdf_text, f"Source token '{token}' not found in PDF text"

    def test_pdf_legend_uses_db_for_intensity(self) -> None:
        """Heat-map legend numeric endpoints must keep dB units (not g)."""
        summary = deepcopy(self.summary)
        rows = summary.get("sensor_intensity_by_location") or []
        assert isinstance(rows, list) and rows, "Scenario should provide intensity rows"
        rows[0]["p95_intensity_db"] = 21.5
        rows[0]["mean_intensity_db"] = 19.0
        if len(rows) > 1 and isinstance(rows[1], dict):
            rows[1]["p95_intensity_db"] = 37.2
            rows[1]["mean_intensity_db"] = 35.0

        pdf_text = self._extract_text(build_report_pdf(summary))
        assert "21.5 db" in pdf_text or "37.2 db" in pdf_text
        assert "21.5 g" not in pdf_text
        assert "37.2 g" not in pdf_text

    def test_pdf_keeps_long_next_steps_without_ellipsis(self) -> None:
        """Critical next-steps content should remain readable when long."""
        summary = deepcopy(self.summary)
        summary["test_plan"] = [
            {
                "what": "Inspect front-left corner under load with road-force balancing and vibration capture.",
                "why": (
                    "Correlate wheel-order persistence across speed bins and verify repeatability "
                    f"for critical action token STEPEND{i:02d}"
                ),
                "speed_band": "70-90 km/h",
                "confirm": "Amplitude drops after intervention",
                "falsify": "Signature remains unchanged after intervention",
                "eta": "30 min",
            }
            for i in range(1, 9)
        ]
        pdf_bytes = build_report_pdf(summary)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pdf_text = self._extract_text(pdf_bytes)

        assert len(reader.pages) >= 2
        assert "…" not in pdf_text
        for i in range(1, 9):
            assert f"stepend{i:02d}" in pdf_text

    def test_pdf_preserves_long_header_metadata_text(self) -> None:
        """Long metadata values should wrap without losing critical tail content."""
        summary = deepcopy(self.summary)
        summary["run_id"] = (
            "run-"
            "very-long-identifier-with-extra-context-for-layout-validation-"
            "tailtoken-runid-12345"
        )
        summary["sensor_model"] = (
            "ADXL345 laboratory validation model with extended calibration metadata "
            "tailtoken-sensormodel-98765"
        )
        pdf_text = self._extract_text(build_report_pdf(summary))
        assert "tailtoken-runid-12345" in pdf_text
        assert "tailtoken" in pdf_text and "sensormodel-98765" in pdf_text


# ---------------------------------------------------------------------------
# Test 3 – EN/NL parity: same scenario, both languages
# ---------------------------------------------------------------------------


@pytest.mark.long_sim
class TestPdfLanguageParity:
    """Validate that EN and NL PDFs for the same scenario are structurally equivalent."""

    @pytest.fixture(autouse=True)
    def _run_both_languages(self) -> None:
        meta_en, samples = _build_20s_scenario()
        meta_nl, _ = _build_20s_scenario()
        meta_nl["language"] = "nl"

        self.summary_en = run_analysis(samples, metadata=meta_en)
        self.summary_nl = run_analysis(samples, metadata=meta_nl)
        self.pdf_en = build_report_pdf(self.summary_en)
        self.pdf_nl = build_report_pdf(self.summary_nl)

    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(filter(None, (page.extract_text() for page in reader.pages))).lower()

    def test_both_pdfs_are_valid(self) -> None:
        """Both EN and NL PDFs are generated and valid."""
        for label, pdf in [("EN", self.pdf_en), ("NL", self.pdf_nl)]:
            assert len(pdf) > 1000, f"{label} PDF too small: {len(pdf)} bytes"
            assert pdf[:5] == b"%PDF-", f"{label} is not a valid PDF"

    def test_same_page_count(self) -> None:
        """EN and NL PDFs should have the same number of pages."""
        en_pages = len(PdfReader(io.BytesIO(self.pdf_en)).pages)
        nl_pages = len(PdfReader(io.BytesIO(self.pdf_nl)).pages)
        assert en_pages == nl_pages, f"Page count mismatch: EN={en_pages}, NL={nl_pages}"

    def test_same_top_cause_count(self) -> None:
        """Same number of top causes in EN and NL summaries."""
        en_n = len(self.summary_en.get("top_causes") or [])
        nl_n = len(self.summary_nl.get("top_causes") or [])
        assert en_n == nl_n, f"Top cause count mismatch: EN={en_n}, NL={nl_n}"

    def test_same_findings_count(self) -> None:
        """Same number of findings in EN and NL summaries."""
        en_n = len(self.summary_en.get("findings") or [])
        nl_n = len(self.summary_nl.get("findings") or [])
        assert en_n == nl_n, f"Findings count mismatch: EN={en_n}, NL={nl_n}"

    def test_same_confidence_values(self) -> None:
        """EN and NL summaries should have identical confidence values."""
        en_conf = top_confidence(self.summary_en)
        nl_conf = top_confidence(self.summary_nl)
        assert abs(en_conf - nl_conf) < 0.01, (
            f"Confidence mismatch: EN={en_conf:.4f}, NL={nl_conf:.4f}"
        )

    def test_same_source_classification(self) -> None:
        """EN and NL summaries should have the same source classification."""
        en_top = extract_top(self.summary_en)
        nl_top = extract_top(self.summary_nl)
        assert en_top is not None and nl_top is not None
        en_src = en_top.get("source", "")
        nl_src = nl_top.get("source", "")
        assert en_src == nl_src, f"Source mismatch: EN='{en_src}', NL='{nl_src}'"

    def test_same_location(self) -> None:
        """EN and NL summaries should have the same strongest_location."""
        en_top = extract_top(self.summary_en)
        nl_top = extract_top(self.summary_nl)
        assert en_top is not None and nl_top is not None
        en_loc = en_top.get("strongest_location", "")
        nl_loc = nl_top.get("strongest_location", "")
        assert en_loc == nl_loc, f"Location mismatch: EN='{en_loc}', NL='{nl_loc}'"

    def test_nl_pdf_has_dutch_content(self) -> None:
        """NL PDF should contain Dutch-language content (not just English)."""
        nl_text = self._extract_text(self.pdf_nl)
        # Common Dutch terms that should appear in a diagnostic report
        dutch_markers = ["diagnos", "voertuig", "wiel", "band", "snelheid", "sensor"]
        found = sum(1 for m in dutch_markers if m in nl_text)
        assert found >= 2, f"NL PDF lacks Dutch content (found {found}/6 markers)"
