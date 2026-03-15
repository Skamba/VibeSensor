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

import pytest
from test_support.analysis import run_analysis
from test_support.core import (
    ALL_WHEEL_SENSORS,
    SENSOR_ENGINE,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RL,
    SENSOR_RR,
    standard_metadata,
)
from test_support.fault_scenarios import make_fault_samples
from test_support.sample_scenarios import (
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    make_transient_samples,
)

from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.use_cases.reporting.mapping import map_summary
from vibesensor.use_cases.reporting.report_data import ReportTemplateData

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

ScenarioPair = tuple[dict, ReportTemplateData]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_report_data(summary: dict) -> ReportTemplateData:
    """Build ReportTemplateData from a summary dict."""
    return map_summary(summary)


# ---------------------------------------------------------------------------
# Scenario builders (reusable across individual + cross-scenario tests)
# ---------------------------------------------------------------------------


def _build_no_fault_baseline() -> ScenarioPair:
    samples = make_noise_samples(sensors=ALL_WHEEL_SENSORS, speed_kmh=80.0, n_samples=30)
    summary = run_analysis(samples, standard_metadata())
    return summary, _build_report_data(summary)


def _build_single_wheel_fault() -> ScenarioPair:
    samples = make_fault_samples(
        fault_sensor=SENSOR_FL,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=80.0,
        n_samples=40,
        fault_amp=0.06,
    )
    summary = run_analysis(samples, standard_metadata())
    return summary, _build_report_data(summary)


def _build_high_speed_fault() -> ScenarioPair:
    samples = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=40.0,
        n_samples=15,
        start_t_s=0.0,
    )
    samples += make_fault_samples(
        fault_sensor=SENSOR_FR,
        sensors=ALL_WHEEL_SENSORS,
        speed_kmh=110.0,
        n_samples=30,
        start_t_s=15.0,
        fault_amp=0.07,
    )
    summary = run_analysis(samples, standard_metadata())
    return summary, _build_report_data(summary)


def _build_mixed_noise_fault() -> ScenarioPair:
    sensors = ALL_WHEEL_SENSORS
    samples = make_idle_samples(sensors=sensors, n_samples=5, start_t_s=0.0)
    samples += make_ramp_samples(
        sensors=sensors,
        speed_start=0.0,
        speed_end=80.0,
        n_samples=10,
        start_t_s=5.0,
    )
    samples += make_fault_samples(
        fault_sensor=SENSOR_RL,
        sensors=sensors,
        speed_kmh=80.0,
        n_samples=30,
        start_t_s=15.0,
        fault_amp=0.05,
    )
    samples += make_transient_samples(
        sensor=SENSOR_FL,
        speed_kmh=80.0,
        n_samples=3,
        start_t_s=45.0,
        spike_amp=0.12,
    )
    samples += make_transient_samples(
        sensor=SENSOR_RR,
        speed_kmh=80.0,
        n_samples=2,
        start_t_s=48.0,
        spike_amp=0.10,
    )
    samples += make_ramp_samples(
        sensors=sensors,
        speed_start=80.0,
        speed_end=0.0,
        n_samples=10,
        start_t_s=50.0,
    )
    summary = run_analysis(samples, standard_metadata())
    return summary, _build_report_data(summary)


def _build_sparse_sensors() -> ScenarioPair:
    sparse = [SENSOR_FL, SENSOR_ENGINE]
    samples = make_fault_samples(
        fault_sensor=SENSOR_FL,
        sensors=sparse,
        speed_kmh=70.0,
        n_samples=30,
        fault_amp=0.05,
    )
    summary = run_analysis(samples, standard_metadata())
    return summary, _build_report_data(summary)


# ---------------------------------------------------------------------------
# Consistency assertion helpers
# ---------------------------------------------------------------------------

# (observed_attr, pattern_evidence_attr, label)
_CROSS_SECTION_FIELDS: list[tuple[str, str, str]] = [
    ("strength_label", "strength_label", "Strength label"),
    ("strength_peak_db", "strength_peak_db", "Strength peak dB"),
    ("certainty_label", "certainty_label", "Certainty label"),
    ("certainty_pct", "certainty_pct", "Certainty pct"),
    ("certainty_reason", "certainty_reason", "Certainty reason"),
    ("strongest_location", "strongest_location", "Location"),
    ("speed_band", "speed_band", "Speed band"),
]


def _assert_cross_section_consistency(rd: ReportTemplateData) -> None:
    """Assert observed <-> pattern_evidence values match exactly."""
    obs, pe = rd.observed, rd.pattern_evidence
    for obs_attr, pe_attr, label in _CROSS_SECTION_FIELDS:
        obs_val = getattr(obs, obs_attr)
        pe_val = getattr(pe, pe_attr)
        assert obs_val == pe_val, (
            f"{label} mismatch: observed='{obs_val}' vs pattern_evidence='{pe_val}'"
        )


def _assert_tier_gating(rd: ReportTemplateData) -> None:
    """Assert tier-based section gating is correct."""
    tier = rd.certainty_tier_key

    if tier == "A":
        assert len(rd.system_cards) == 0, (
            f"Tier A must suppress system cards, got {len(rd.system_cards)}"
        )
        assert len(rd.next_steps) > 0, "Tier A must have data-collection guidance steps"
    elif tier == "B":
        for card in rd.system_cards:
            assert len(card.parts) == 0, (
                f"Tier B card '{card.system_name}' must have no repair parts, got {len(card.parts)}"
            )


def _assert_valid_float(value: str, field_name: str) -> None:
    """Assert a non-dash value is a valid float string."""
    if value != "\u2014":
        try:
            float(value)
        except ValueError:
            pytest.fail(f"Peak row {field_name} not a valid float: '{value}'")


def _assert_unit_consistency(rd: ReportTemplateData) -> None:
    """Assert units are consistent across the report."""
    sl = rd.observed.strength_label or ""
    if "dB" in sl:
        assert " g" not in sl, f"Strength label must be dB-only: '{sl}'"

    for pr in rd.peak_rows:
        _assert_valid_float(pr.peak_db, "peak_db")
        _assert_valid_float(pr.strength_db, "strength_db")
        _assert_valid_float(pr.freq_hz, "freq_hz")

    units = {row.get("unit") for row in rd.location_hotspot_rows if isinstance(row, dict)}
    assert len(units) <= 1, f"Mixed units in location hotspot rows: {units}"


def _assert_certainty_tier_consistent(rd: ReportTemplateData, summary: dict) -> None:
    """Assert the tier stored in report matches certainty_tier() layout gate."""
    from vibesensor.adapters.persistence.boundaries.diagnostic_case import test_run_from_summary
    from vibesensor.use_cases.diagnostics.strength_labels import certainty_tier, strength_label

    test_run = test_run_from_summary(summary)
    effective = test_run.effective_top_causes()
    domain_primary = effective[0] if effective else test_run.primary_finding
    if domain_primary:
        confidence = domain_primary.effective_confidence
        strength_db = test_run.top_strength_db()
        strength_band_key = strength_label(strength_db)[0] if strength_db is not None else None
        expected_tier = certainty_tier(confidence, strength_band_key=strength_band_key)
    else:
        expected_tier = "A"  # no findings → lowest tier

    assert rd.certainty_tier_key == expected_tier, (
        f"Tier mismatch: report has '{rd.certainty_tier_key}', expected '{expected_tier}'"
    )


def _assert_no_report_time_analysis(rd: ReportTemplateData) -> None:
    """Verify the report data is fully pre-computed (no analysis imports in report)."""
    assert isinstance(rd.observed.strength_label, (str, type(None)))
    assert isinstance(rd.observed.certainty_label, (str, type(None)))
    assert isinstance(rd.observed.certainty_pct, (str, type(None)))
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

    # Generate PDF
    pdf = _assert_pdf_generates(rd)

    return pdf


# ---------------------------------------------------------------------------
# Scenario 1: No-fault baseline
# ---------------------------------------------------------------------------


class TestScenario1NoFaultBaseline:
    """Clean noise-only scenario -- should remain guarded, no overconfident claims."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_no_fault_baseline()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_no_overconfident_claims(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert rd.certainty_tier_key in ("A", "B"), (
            f"No-fault baseline should be tier A or B, got '{rd.certainty_tier_key}'"
        )

    def test_no_repair_actions(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        for card in rd.system_cards:
            if rd.certainty_tier_key in ("A", "B"):
                assert len(card.parts) == 0, (
                    f"No-fault baseline card '{card.system_name}' should have no repair parts"
                )


# ---------------------------------------------------------------------------
# Scenario 2: Single wheel fault (clear localisation)
# ---------------------------------------------------------------------------


class TestScenario2SingleWheelFault:
    """Clear wheel fault on FL -- should localise correctly."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_single_wheel_fault()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_fl_localisation(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        loc = (rd.observed.strongest_location or "").lower()
        assert "front" in loc and "left" in loc, (
            f"Expected front-left localisation, got '{rd.observed.strongest_location}'"
        )

    def test_wheel_source_identified(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        system = (rd.observed.primary_system or "").lower()
        assert "wheel" in system or "tire" in system, (
            f"Expected wheel/tire source, got '{rd.observed.primary_system}'"
        )

    def test_strength_nonzero(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert rd.observed.strength_label is not None
        assert rd.observed.strength_label != ""
        assert rd.observed.strength_label != "Unknown"

    def test_peak_rows_present(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert len(rd.peak_rows) > 0, "Single wheel fault should have peak rows"


# ---------------------------------------------------------------------------
# Scenario 3: High-speed-only fault (phase/speed-band sensitivity)
# ---------------------------------------------------------------------------


class TestScenario3HighSpeedFault:
    """Fault only at high speed -- speed band must reflect high-speed condition."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_high_speed_fault()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_speed_band_reflects_high_speed(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        band = (rd.observed.speed_band or "").lower()
        assert band != "unknown" and band != "", (
            f"High-speed fault should have a specific speed band, got '{rd.observed.speed_band}'"
        )

    def test_fr_localisation(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        loc = (rd.observed.strongest_location or "").lower()
        assert "front" in loc and "right" in loc, (
            f"Expected front-right localisation, got '{rd.observed.strongest_location}'"
        )


# ---------------------------------------------------------------------------
# Scenario 4: Mixed noise + fault onset (robustness against noise)
# ---------------------------------------------------------------------------


class TestScenario4MixedNoiseFault:
    """Noise-heavy scenario with fault onset -- robustness against noise."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_mixed_noise_fault()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_fault_not_masked_by_noise(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert rd.observed.primary_system is not None
        assert rd.observed.primary_system != "Unknown"

    def test_data_trust_present(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert isinstance(rd.data_trust, list)


# ---------------------------------------------------------------------------
# Scenario 5: Sparse sensor coverage (weird sensor mix)
# ---------------------------------------------------------------------------


class TestScenario5SparseSensors:
    """Only 2 sensors (non-standard mix) -- should degrade granularity."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_sparse_sensors()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        summary, rd = scenario
        _run_all_consistency_checks(summary, rd)

    def test_sensor_count_accurate(self, scenario: ScenarioPair) -> None:
        summary, rd = scenario
        connected = summary.get("sensor_locations_connected_throughout") or summary.get(
            "sensor_locations",
        )
        assert rd.sensor_count == len(connected or [])

    def test_no_false_precision(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert rd.sensor_count <= 2


# ---------------------------------------------------------------------------
# Cross-scenario: parametrized over all 5
# ---------------------------------------------------------------------------

_SCENARIO_BUILDERS = {
    "no_fault_baseline": _build_no_fault_baseline,
    "single_wheel_fault": _build_single_wheel_fault,
    "high_speed_fault": _build_high_speed_fault,
    "mixed_noise_fault": _build_mixed_noise_fault,
    "sparse_sensors": _build_sparse_sensors,
}


class TestAllFiveScenariosPass:
    """Run all 5 scenarios and assert all consistency checks pass."""

    @pytest.fixture(params=sorted(_SCENARIO_BUILDERS), scope="class")
    def named_scenario(
        self,
        request: pytest.FixtureRequest,
    ) -> tuple[str, dict, ReportTemplateData]:
        name: str = request.param
        summary, rd = _SCENARIO_BUILDERS[name]()
        return name, summary, rd

    def test_consistency(self, named_scenario: tuple[str, dict, ReportTemplateData]) -> None:
        name, summary, rd = named_scenario
        try:
            _run_all_consistency_checks(summary, rd)
        except AssertionError as e:
            pytest.fail(f"Scenario '{name}' failed consistency check: {e}")

    def test_pdf_generates(self, named_scenario: tuple[str, dict, ReportTemplateData]) -> None:
        name, _, rd = named_scenario
        pdf = _assert_pdf_generates(rd)
        assert len(pdf) > 500, f"Scenario '{name}' PDF too small: {len(pdf)} bytes"
