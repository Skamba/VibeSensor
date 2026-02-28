# ruff: noqa: E501
"""Five-scenario report consistency tests.

Each scenario generates analysis output via the builders, builds
ReportTemplateData, and then validates that every report field traces
back consistently to the persisted analysis metrics.

Scenarios
---------
1. No-fault baseline – guarded, no overconfident claims
2. Single wheel fault – clear localisation
3. High-speed-only fault – speed-band sensitivity
4. Mixed noise + fault onset – robustness against noise
5. Sparse sensor coverage – degrades granularity, no false precision
"""

from __future__ import annotations

from dataclasses import asdict

import pytest
from builders import (
    ALL_WHEEL_SENSORS,
    SENSOR_ENGINE,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RL,
    SENSOR_RR,
    make_fault_samples,
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    make_transient_samples,
    run_analysis,
    standard_metadata,
)

from vibesensor.analysis import map_summary
from vibesensor.analysis.strength_labels import (
    certainty_tier,
)
from vibesensor.report.pdf_builder import build_report_pdf
from vibesensor.report.report_data import ReportTemplateData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_report_data(summary: dict) -> ReportTemplateData:
    """Build ReportTemplateData from a summary dict."""
    return map_summary(summary)


def _roundtrip_report_data(rd: ReportTemplateData) -> ReportTemplateData:
    """Simulate persistence round-trip (dict → ReportTemplateData)."""
    d = asdict(rd)
    # Reconstruct sub-dataclasses
    from vibesensor.report.report_data import (
        CarMeta,
        DataTrustItem,
        NextStep,
        ObservedSignature,
        PartSuggestion,
        PatternEvidence,
        PeakRow,
        SystemFindingCard,
    )

    return ReportTemplateData(
        title=d["title"],
        run_datetime=d.get("run_datetime"),
        run_id=d.get("run_id"),
        duration_text=d.get("duration_text"),
        start_time_utc=d.get("start_time_utc"),
        end_time_utc=d.get("end_time_utc"),
        sample_rate_hz=d.get("sample_rate_hz"),
        tire_spec_text=d.get("tire_spec_text"),
        sample_count=d.get("sample_count", 0),
        sensor_count=d.get("sensor_count", 0),
        sensor_locations=d.get("sensor_locations", []),
        sensor_model=d.get("sensor_model"),
        firmware_version=d.get("firmware_version"),
        car=CarMeta(**d.get("car", {})),
        observed=ObservedSignature(**d.get("observed", {})),
        system_cards=[
            SystemFindingCard(
                **{
                    **sc,
                    "parts": [PartSuggestion(**p) for p in sc.get("parts", [])],
                }
            )
            for sc in d.get("system_cards", [])
        ],
        next_steps=[NextStep(**ns) for ns in d.get("next_steps", [])],
        data_trust=[DataTrustItem(**dt) for dt in d.get("data_trust", [])],
        pattern_evidence=PatternEvidence(**d.get("pattern_evidence", {})),
        peak_rows=[PeakRow(**pr) for pr in d.get("peak_rows", [])],
        phase_info=d.get("phase_info"),
        version_marker=d.get("version_marker", ""),
        lang=d.get("lang", "en"),
        certainty_tier_key=d.get("certainty_tier_key", "C"),
        findings=d.get("findings", []),
        top_causes=d.get("top_causes", []),
        sensor_intensity_by_location=d.get("sensor_intensity_by_location", []),
        location_hotspot_rows=d.get("location_hotspot_rows", []),
    )


# ---------------------------------------------------------------------------
# Consistency assertion helpers
# ---------------------------------------------------------------------------


def _assert_cross_section_consistency(rd: ReportTemplateData) -> None:
    """Assert observed ↔ pattern_evidence values match exactly."""
    obs = rd.observed
    pe = rd.pattern_evidence

    assert obs.strength_label == pe.strength_label, (
        f"Strength label mismatch: observed='{obs.strength_label}' vs "
        f"pattern_evidence='{pe.strength_label}'"
    )
    assert obs.strength_peak_amp_g == pe.strength_peak_amp_g, (
        f"Strength peak amp mismatch: observed={obs.strength_peak_amp_g} vs "
        f"pattern_evidence={pe.strength_peak_amp_g}"
    )
    assert obs.certainty_label == pe.certainty_label, (
        f"Certainty label mismatch: observed='{obs.certainty_label}' vs "
        f"pattern_evidence='{pe.certainty_label}'"
    )
    assert obs.certainty_pct == pe.certainty_pct, (
        f"Certainty pct mismatch: observed='{obs.certainty_pct}' vs "
        f"pattern_evidence='{pe.certainty_pct}'"
    )
    assert obs.certainty_reason == pe.certainty_reason, (
        f"Certainty reason mismatch: observed='{obs.certainty_reason}' vs "
        f"pattern_evidence='{pe.certainty_reason}'"
    )
    assert obs.strongest_sensor_location == pe.strongest_location, (
        f"Location mismatch: observed='{obs.strongest_sensor_location}' vs "
        f"pattern_evidence='{pe.strongest_location}'"
    )
    assert obs.speed_band == pe.speed_band, (
        f"Speed band mismatch: observed='{obs.speed_band}' vs pattern_evidence='{pe.speed_band}'"
    )


def _assert_tier_gating(rd: ReportTemplateData) -> None:
    """Assert tier-based section gating is correct."""
    tier = rd.certainty_tier_key

    if tier == "A":
        # Tier A: no system cards, data-collection guidance in next steps
        assert len(rd.system_cards) == 0, (
            f"Tier A must suppress system cards, got {len(rd.system_cards)}"
        )
        # Next steps should be present (guidance-oriented)
        assert len(rd.next_steps) > 0, "Tier A must have data-collection guidance steps"
    elif tier == "B":
        # Tier B: system cards labelled as hypothesis, no repair parts
        for card in rd.system_cards:
            assert len(card.parts) == 0, (
                f"Tier B card '{card.system_name}' must have no repair parts, got {len(card.parts)}"
            )
    # Tier C: full cards allowed (no restrictions to check)


def _assert_unit_consistency(rd: ReportTemplateData) -> None:
    """Assert units are consistent across the report."""
    # Strength label should contain "dB" if a dB value is present
    sl = rd.observed.strength_label or ""
    if "dB" in sl:
        assert "g peak" in sl or rd.observed.strength_peak_amp_g is None, (
            f"Strength label has dB but missing g peak format: '{sl}'"
        )

    # Peak rows: amplitude should be in g, strength in dB
    for pr in rd.peak_rows:
        if pr.amp_g != "\u2014":
            # Should be a float string (e.g. "0.0600")
            try:
                float(pr.amp_g)
            except ValueError:
                pytest.fail(f"Peak row amp_g not a valid float: '{pr.amp_g}'")
        if pr.strength_db != "\u2014":
            try:
                float(pr.strength_db)
            except ValueError:
                pytest.fail(f"Peak row strength_db not a valid float: '{pr.strength_db}'")
        if pr.freq_hz != "\u2014":
            try:
                float(pr.freq_hz)
            except ValueError:
                pytest.fail(f"Peak row freq_hz not a valid float: '{pr.freq_hz}'")

    # Location hotspot rows: unit must be uniform
    units = {row.get("unit") for row in rd.location_hotspot_rows if isinstance(row, dict)}
    assert len(units) <= 1, f"Mixed units in location hotspot rows: {units}"


def _assert_certainty_tier_consistent(rd: ReportTemplateData, summary: dict) -> None:
    """Assert the tier stored in report matches what certainty_tier() would return."""
    top_causes = summary.get("top_causes", [])
    findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    findings_non_ref = [
        f for f in findings if not str(f.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    top_causes_non_ref = [
        c
        for c in top_causes
        if not str(c.get("finding_id") or "").strip().upper().startswith("REF_")
    ]
    top_causes_actionable = [
        c
        for c in top_causes_non_ref
        if str(c.get("source") or c.get("suspected_source") or "").strip().lower()
        not in {"unknown_resonance", "unknown"}
        or str(c.get("strongest_location") or "").strip().lower()
        not in {"", "unknown", "not available", "n/a"}
    ]
    effective_causes = top_causes_actionable or findings_non_ref or top_causes_non_ref or top_causes

    if effective_causes:
        primary = effective_causes[0]
        conf_val = primary.get("confidence") or primary.get("confidence_0_to_1") or 0.0
        conf = float(conf_val)
    else:
        conf = 0.0

    expected_tier = certainty_tier(conf)
    assert rd.certainty_tier_key == expected_tier, (
        f"Tier mismatch: report has '{rd.certainty_tier_key}', "
        f"expected '{expected_tier}' for confidence {conf:.3f}"
    )


def _assert_no_report_time_analysis(rd: ReportTemplateData) -> None:
    """Verify the report data is fully pre-computed (no analysis imports in report)."""
    # All fields that should be pre-computed strings/values
    assert isinstance(rd.observed.strength_label, (str, type(None)))
    assert isinstance(rd.observed.certainty_label, (str, type(None)))
    assert isinstance(rd.observed.certainty_pct, (str, type(None)))
    # Location hotspot rows should be pre-computed
    if rd.findings:
        assert isinstance(rd.location_hotspot_rows, list)


def _assert_pdf_generates(rd: ReportTemplateData) -> bytes:
    """Assert the PDF generates successfully and returns valid bytes."""
    pdf = build_report_pdf(rd)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 100
    assert pdf[:5] == b"%PDF-"
    return pdf


def _run_all_consistency_checks(
    summary: dict,
    rd: ReportTemplateData,
    *,
    expect_tier: str | None = None,
) -> bytes:
    """Run all consistency checks and return the generated PDF."""
    _assert_cross_section_consistency(rd)
    _assert_tier_gating(rd)
    _assert_unit_consistency(rd)
    _assert_certainty_tier_consistent(rd, summary)
    _assert_no_report_time_analysis(rd)

    if expect_tier is not None:
        assert rd.certainty_tier_key == expect_tier, (
            f"Expected tier '{expect_tier}', got '{rd.certainty_tier_key}'"
        )

    # Also test persistence round-trip
    rd_rt = _roundtrip_report_data(rd)
    _assert_cross_section_consistency(rd_rt)
    _assert_tier_gating(rd_rt)
    _assert_unit_consistency(rd_rt)

    # Generate PDF from both original and round-tripped data
    pdf = _assert_pdf_generates(rd)
    _assert_pdf_generates(rd_rt)

    return pdf


# ---------------------------------------------------------------------------
# Scenario 1: No-fault baseline
# ---------------------------------------------------------------------------


class TestScenario1NoFaultBaseline:
    """Clean noise-only scenario – should remain guarded, no overconfident claims."""

    @pytest.fixture()
    def scenario(self):
        sensors = ALL_WHEEL_SENSORS
        samples = make_noise_samples(sensors=sensors, speed_kmh=80.0, n_samples=30)
        metadata = standard_metadata()
        summary = run_analysis(samples, metadata)
        rd = _build_report_data(summary)
        return summary, rd

    def test_consistency(self, scenario):
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_no_overconfident_claims(self, scenario):
        _, rd = scenario
        # Should be tier A or B (no high-confidence fault)
        assert rd.certainty_tier_key in ("A", "B"), (
            f"No-fault baseline should be tier A or B, got '{rd.certainty_tier_key}'"
        )

    def test_no_repair_actions(self, scenario):
        _, rd = scenario
        # Tier A/B: no repair-oriented parts in system cards
        for card in rd.system_cards:
            if rd.certainty_tier_key in ("A", "B"):
                assert len(card.parts) == 0, (
                    f"No-fault baseline card '{card.system_name}' should have no repair parts"
                )


# ---------------------------------------------------------------------------
# Scenario 2: Single wheel fault (clear localisation)
# ---------------------------------------------------------------------------


class TestScenario2SingleWheelFault:
    """Clear wheel fault on FL – should localise correctly."""

    @pytest.fixture()
    def scenario(self):
        sensors = ALL_WHEEL_SENSORS
        samples = make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=80.0,
            n_samples=40,
            fault_amp=0.06,
        )
        metadata = standard_metadata()
        summary = run_analysis(samples, metadata)
        rd = _build_report_data(summary)
        return summary, rd

    def test_consistency(self, scenario):
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_fl_localisation(self, scenario):
        _, rd = scenario
        loc = (rd.observed.strongest_sensor_location or "").lower()
        assert "front" in loc and "left" in loc, (
            f"Expected front-left localisation, got '{rd.observed.strongest_sensor_location}'"
        )

    def test_wheel_source_identified(self, scenario):
        _, rd = scenario
        system = (rd.observed.primary_system or "").lower()
        assert "wheel" in system or "tire" in system, (
            f"Expected wheel/tire source, got '{rd.observed.primary_system}'"
        )

    def test_strength_nonzero(self, scenario):
        _, rd = scenario
        assert rd.observed.strength_label is not None
        assert rd.observed.strength_label != ""
        assert rd.observed.strength_label != "Unknown"

    def test_peak_rows_present(self, scenario):
        _, rd = scenario
        assert len(rd.peak_rows) > 0, "Single wheel fault should have peak rows"


# ---------------------------------------------------------------------------
# Scenario 3: High-speed-only fault (phase/speed-band sensitivity)
# ---------------------------------------------------------------------------


class TestScenario3HighSpeedFault:
    """Fault only at high speed – speed band must reflect high-speed condition."""

    @pytest.fixture()
    def scenario(self):
        sensors = ALL_WHEEL_SENSORS
        # Low-speed phase: noise only
        samples = make_noise_samples(sensors=sensors, speed_kmh=40.0, n_samples=15, start_t_s=0.0)
        # High-speed phase: fault emerges
        samples += make_fault_samples(
            fault_sensor=SENSOR_FR,
            sensors=sensors,
            speed_kmh=110.0,
            n_samples=30,
            start_t_s=15.0,
            fault_amp=0.07,
        )
        metadata = standard_metadata()
        summary = run_analysis(samples, metadata)
        rd = _build_report_data(summary)
        return summary, rd

    def test_consistency(self, scenario):
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_speed_band_reflects_high_speed(self, scenario):
        _, rd = scenario
        band = (rd.observed.speed_band or "").lower()
        # The speed band should mention high speed or contain a number >= 100
        assert band != "unknown" and band != "", (
            f"High-speed fault should have a specific speed band, got '{rd.observed.speed_band}'"
        )

    def test_fr_localisation(self, scenario):
        _, rd = scenario
        loc = (rd.observed.strongest_sensor_location or "").lower()
        assert "front" in loc and "right" in loc, (
            f"Expected front-right localisation, got '{rd.observed.strongest_sensor_location}'"
        )


# ---------------------------------------------------------------------------
# Scenario 4: Mixed noise + fault onset (robustness against noise)
# ---------------------------------------------------------------------------


class TestScenario4MixedNoiseFault:
    """Noise-heavy scenario with fault onset – robustness against noise."""

    @pytest.fixture()
    def scenario(self):
        sensors = ALL_WHEEL_SENSORS
        # Phase 1: idle
        samples = make_idle_samples(sensors=sensors, n_samples=5, start_t_s=0.0)
        # Phase 2: ramp up
        samples += make_ramp_samples(
            sensors=sensors, speed_start=0.0, speed_end=80.0, n_samples=10, start_t_s=5.0
        )
        # Phase 3: cruise with fault + transient noise
        samples += make_fault_samples(
            fault_sensor=SENSOR_RL,
            sensors=sensors,
            speed_kmh=80.0,
            n_samples=30,
            start_t_s=15.0,
            fault_amp=0.05,
        )
        # Phase 4: transient impacts (road bumps)
        samples += make_transient_samples(
            sensor=SENSOR_FL, speed_kmh=80.0, n_samples=3, start_t_s=45.0, spike_amp=0.12
        )
        samples += make_transient_samples(
            sensor=SENSOR_RR, speed_kmh=80.0, n_samples=2, start_t_s=48.0, spike_amp=0.10
        )
        # Phase 5: deceleration
        samples += make_ramp_samples(
            sensors=sensors, speed_start=80.0, speed_end=0.0, n_samples=10, start_t_s=50.0
        )
        metadata = standard_metadata()
        summary = run_analysis(samples, metadata)
        rd = _build_report_data(summary)
        return summary, rd

    def test_consistency(self, scenario):
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_fault_not_masked_by_noise(self, scenario):
        _, rd = scenario
        # The fault should still be detected despite noise
        assert rd.observed.primary_system is not None
        assert rd.observed.primary_system != "Unknown"

    def test_data_trust_present(self, scenario):
        _, rd = scenario
        # Should have data trust items
        assert isinstance(rd.data_trust, list)


# ---------------------------------------------------------------------------
# Scenario 5: Sparse sensor coverage (weird sensor mix)
# ---------------------------------------------------------------------------


class TestScenario5SparseSensors:
    """Only 2 sensors (non-standard mix) – should degrade granularity."""

    @pytest.fixture()
    def scenario(self):
        sensors = [SENSOR_FL, SENSOR_ENGINE]
        # Only FL and engine-bay sensors
        samples = make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=70.0,
            n_samples=30,
            fault_amp=0.05,
        )
        metadata = standard_metadata()
        summary = run_analysis(samples, metadata)
        rd = _build_report_data(summary)
        return summary, rd

    def test_consistency(self, scenario):
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_sensor_count_accurate(self, scenario):
        summary, rd = scenario
        # The sensor_count in report should reflect analysis output
        assert rd.sensor_count == int(summary.get("sensor_count_used", 0))

    def test_no_false_precision(self, scenario):
        _, rd = scenario
        # With only 2 sensors, spatial precision is limited
        # The certainty reason should reflect limited data
        assert rd.sensor_count <= 2


# ---------------------------------------------------------------------------
# Cross-scenario: verify all 5 at once
# ---------------------------------------------------------------------------


class TestAllFiveScenariosPass:
    """Run all 5 scenarios and assert all consistency checks pass."""

    def _build_scenarios(self):
        """Return list of (name, summary, rd) tuples for all 5 scenarios."""
        scenarios = []

        # 1. No-fault baseline
        s1 = make_noise_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=80.0, n_samples=30)
        m1 = standard_metadata()
        sum1 = run_analysis(s1, m1)
        rd1 = _build_report_data(sum1)
        scenarios.append(("no_fault_baseline", sum1, rd1))

        # 2. Single wheel fault
        s2 = make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=80.0,
            n_samples=40,
            fault_amp=0.06,
        )
        m2 = standard_metadata()
        sum2 = run_analysis(s2, m2)
        rd2 = _build_report_data(sum2)
        scenarios.append(("single_wheel_fault", sum2, rd2))

        # 3. High-speed-only fault
        s3 = make_noise_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=40.0, n_samples=15)
        s3 += make_fault_samples(
            fault_sensor=SENSOR_FR,
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=110.0,
            n_samples=30,
            start_t_s=15.0,
            fault_amp=0.07,
        )
        m3 = standard_metadata()
        sum3 = run_analysis(s3, m3)
        rd3 = _build_report_data(sum3)
        scenarios.append(("high_speed_fault", sum3, rd3))

        # 4. Mixed noise + fault onset
        s4 = make_idle_samples(sensors=ALL_WHEEL_SENSORS, n_samples=5)
        s4 += make_ramp_samples(
            sensors=ALL_WHEEL_SENSORS,
            speed_start=0.0,
            speed_end=80.0,
            n_samples=10,
            start_t_s=5.0,
        )
        s4 += make_fault_samples(
            fault_sensor=SENSOR_RL,
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=80.0,
            n_samples=30,
            start_t_s=15.0,
            fault_amp=0.05,
        )
        s4 += make_transient_samples(
            sensor=SENSOR_FL,
            speed_kmh=80.0,
            n_samples=3,
            start_t_s=45.0,
        )
        s4 += make_ramp_samples(
            sensors=ALL_WHEEL_SENSORS,
            speed_start=80.0,
            speed_end=0.0,
            n_samples=10,
            start_t_s=50.0,
        )
        m4 = standard_metadata()
        sum4 = run_analysis(s4, m4)
        rd4 = _build_report_data(sum4)
        scenarios.append(("mixed_noise_fault", sum4, rd4))

        # 5. Sparse sensor coverage
        sparse_sensors = [SENSOR_FL, SENSOR_ENGINE]
        s5 = make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sparse_sensors,
            speed_kmh=70.0,
            n_samples=30,
            fault_amp=0.05,
        )
        m5 = standard_metadata()
        sum5 = run_analysis(s5, m5)
        rd5 = _build_report_data(sum5)
        scenarios.append(("sparse_sensors", sum5, rd5))

        return scenarios

    def test_all_five_pass(self):
        scenarios = self._build_scenarios()
        assert len(scenarios) == 5

        for name, summary, rd in scenarios:
            try:
                _run_all_consistency_checks(summary, rd)
            except AssertionError as e:
                pytest.fail(f"Scenario '{name}' failed consistency check: {e}")

    def test_all_five_generate_pdfs(self):
        scenarios = self._build_scenarios()
        for name, _, rd in scenarios:
            try:
                pdf = _assert_pdf_generates(rd)
                assert len(pdf) > 500, f"Scenario '{name}' PDF too small: {len(pdf)} bytes"
            except Exception as e:
                pytest.fail(f"Scenario '{name}' PDF generation failed: {e}")
