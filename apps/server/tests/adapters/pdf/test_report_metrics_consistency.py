"""Five-scenario report consistency tests.

Each scenario generates analysis output via the builders, builds
ReportDocument, and then validates that every report field traces
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
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.use_cases.history.report_document import build_report_document

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

ScenarioPair = tuple[dict, ReportDocument]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_report_data(summary: dict) -> ReportDocument:
    """Build ReportDocument from a summary dict."""
    return build_report_document(prepare_report_input(summary))


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


def _assert_cross_section_consistency(rd: ReportDocument) -> None:
    """Assert observed <-> pattern_evidence values match exactly."""
    obs, pe = rd.observed, rd.pattern_evidence
    for obs_attr, pe_attr, label in _CROSS_SECTION_FIELDS:
        obs_val = getattr(obs, obs_attr)
        pe_val = getattr(pe, pe_attr)
        assert obs_val == pe_val, (
            f"{label} mismatch: observed='{obs_val}' vs pattern_evidence='{pe_val}'"
        )


def _assert_tier_gating(rd: ReportDocument) -> None:
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


def _assert_unit_consistency(rd: ReportDocument) -> None:
    """Assert units are consistent across the report."""
    sl = rd.observed.strength_label or ""
    if "dB" in sl:
        assert " g" not in sl, f"Strength label must be dB-only: '{sl}'"

    for pr in rd.peak_rows:
        _assert_valid_float(pr.peak_db, "peak_db")
        _assert_valid_float(pr.strength_db, "strength_db")
        _assert_valid_float(pr.freq_hz, "freq_hz")

    units = {row.unit for row in rd.location_hotspot_rows}
    assert len(units) <= 1, f"Mixed units in location hotspot rows: {units}"


def _assert_certainty_tier_consistent(rd: ReportDocument, summary: dict) -> None:
    """Assert the tier stored in report matches ConfidenceAssessment.tier."""
    from vibesensor.domain import ConfidenceAssessment
    from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
        test_run_from_summary,
    )
    from vibesensor.shared.report_presentation import strength_label

    test_run = test_run_from_summary(summary)
    effective = test_run.effective_top_causes()
    domain_primary = effective[0] if effective else test_run.primary_finding
    if domain_primary and domain_primary.confidence_assessment:
        expected_tier = domain_primary.confidence_assessment.tier
    elif domain_primary:
        confidence = domain_primary.effective_confidence
        strength_db = test_run.top_strength_db()
        strength_band_key = strength_label(strength_db)[0] if strength_db is not None else None
        expected_tier = ConfidenceAssessment.assess(
            confidence,
            strength_band_key=strength_band_key,
        ).tier
    else:
        expected_tier = "A"

    assert rd.certainty_tier_key == expected_tier, (
        f"Tier mismatch: report has '{rd.certainty_tier_key}', expected '{expected_tier}'"
    )


def _assert_no_report_time_analysis(rd: ReportDocument) -> None:
    """Verify the report data is fully pre-computed (no analysis imports in report)."""
    assert isinstance(rd.observed.strength_label, (str, type(None)))
    assert isinstance(rd.observed.certainty_label, (str, type(None)))
    assert isinstance(rd.observed.certainty_pct, (str, type(None)))
    if rd.findings:
        assert isinstance(rd.location_hotspot_rows, list)


def _assert_pdf_generates(rd: ReportDocument) -> bytes:
    """Assert the PDF generates successfully and returns valid bytes."""
    pdf = build_report_pdf(rd)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 100
    assert pdf[:5] == b"%PDF-"
    return pdf


def _run_all_consistency_checks(
    summary: dict,
    rd: ReportDocument,
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


def _assert_scenario_consistency(scenario: ScenarioPair) -> None:
    """Run the shared consistency checks for a scenario fixture payload."""
    summary, rd = scenario
    _run_all_consistency_checks(summary, rd)


def _warn_checks(rd: ReportDocument) -> set[str]:
    return {item.check for item in rd.data_trust if item.state == "warn"}


# ---------------------------------------------------------------------------
# Scenario 1: No-fault baseline
# ---------------------------------------------------------------------------


class TestScenario1NoFaultBaseline:
    """Clean noise-only scenario -- should remain guarded, no overconfident claims."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_no_fault_baseline()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        _assert_scenario_consistency(scenario)

    def test_no_fault_baseline_stays_guarded(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert rd.certainty_tier_key == "A"
        assert rd.observed.primary_system == "No significant pattern"
        assert rd.system_cards == []
        assert len(rd.next_steps) == 2
        assert _warn_checks(rd) == {
            "Reference completeness",
            "Order-analysis reference context was incomplete for this run",
        }


# ---------------------------------------------------------------------------
# Scenario 2: Single wheel fault (clear localisation)
# ---------------------------------------------------------------------------


class TestScenario2SingleWheelFault:
    """Clear wheel fault on FL -- should localise correctly."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_single_wheel_fault()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        _assert_scenario_consistency(scenario)

    def test_single_wheel_fault_contract(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert rd.certainty_tier_key == "B"
        assert rd.observed.primary_system == "Wheel / Tire"
        assert rd.observed.strongest_location == "Front-Left"
        assert rd.observed.speed_band == "80-90 km/h"
        assert (rd.observed.strength_label or "").startswith("Moderate (")
        assert (rd.observed.strength_label or "").endswith(" dB)")
        assert rd.system_cards[0].status_label == "Possible source"
        first_peak = rd.peak_rows[0]
        assert first_peak.relevance == "Repeated pattern"
        assert first_peak.speed_band == "80-90 km/h"
        assert first_peak.peak_db != "\u2014"


# ---------------------------------------------------------------------------
# Scenario 3: High-speed-only fault (phase/speed-band sensitivity)
# ---------------------------------------------------------------------------


class TestScenario3HighSpeedFault:
    """Fault only at high speed -- speed band must reflect high-speed condition."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_high_speed_fault()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        _assert_scenario_consistency(scenario)

    def test_high_speed_fault_tracks_high_band_and_uncertainty_reason(
        self,
        scenario: ScenarioPair,
    ) -> None:
        _, rd = scenario
        assert rd.observed.primary_system == "Wheel / Tire"
        assert rd.observed.strongest_location == "Front-Right"
        assert rd.observed.speed_band == "110-120 km/h"
        assert rd.observed.certainty_label == "High"
        assert rd.observed.certainty_reason == (
            "Missing reference data may affect accuracy; Speed was not steady during measurement"
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
        _assert_scenario_consistency(scenario)

    def test_fault_not_masked_by_noise(self, scenario: ScenarioPair) -> None:
        _, rd = scenario
        assert rd.observed.primary_system == "Wheel / Tire"
        assert rd.observed.strongest_location == "Rear-Left"
        assert rd.observed.speed_band == "80-90 km/h"
        assert rd.observed.certainty_label == "Medium"
        assert _warn_checks(rd) == {
            "Reference completeness",
            "Order-analysis reference context was incomplete for this run",
        }


# ---------------------------------------------------------------------------
# Scenario 5: Sparse sensor coverage (weird sensor mix)
# ---------------------------------------------------------------------------


class TestScenario5SparseSensors:
    """Only 2 sensors (non-standard mix) -- should degrade granularity."""

    @pytest.fixture
    def scenario(self) -> ScenarioPair:
        return _build_sparse_sensors()

    def test_consistency(self, scenario: ScenarioPair) -> None:
        _assert_scenario_consistency(scenario)

    def test_sensor_count_accurate(self, scenario: ScenarioPair) -> None:
        summary, rd = scenario
        connected = summary.get("sensor_locations_connected_throughout") or summary.get(
            "sensor_locations",
        )
        assert rd.sensor_count == len(connected or [])

    def test_sparse_sensor_contract_degrades_location_granularity(
        self,
        scenario: ScenarioPair,
    ) -> None:
        _, rd = scenario
        assert rd.sensor_count == 2
        assert sorted(rd.sensor_locations) == ["engine-bay", "front-left"]
        assert {row.location for row in rd.location_hotspot_rows} == {
            "engine-bay",
            "front-left",
        }
        assert {row.unit for row in rd.location_hotspot_rows} == {"db"}


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


@pytest.mark.xdist_group(name="report_metrics_consistency")
class TestAllFiveScenariosPass:
    """Run all 5 scenarios and assert all consistency checks pass."""

    @pytest.fixture(params=sorted(_SCENARIO_BUILDERS), scope="class")
    def named_scenario(
        self,
        request: pytest.FixtureRequest,
    ) -> tuple[str, dict, ReportDocument]:
        name: str = request.param
        summary, rd = _SCENARIO_BUILDERS[name]()
        return name, summary, rd

    def test_consistency(self, named_scenario: tuple[str, dict, ReportDocument]) -> None:
        name, summary, rd = named_scenario
        try:
            _run_all_consistency_checks(summary, rd)
        except AssertionError as e:
            pytest.fail(f"Scenario '{name}' failed consistency check: {e}")

    def test_pdf_generates(self, named_scenario: tuple[str, dict, ReportDocument]) -> None:
        name, _, rd = named_scenario
        pdf = _assert_pdf_generates(rd)
        assert len(pdf) > 500, f"Scenario '{name}' PDF too small: {len(pdf)} bytes"
