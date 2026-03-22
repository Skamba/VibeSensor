"""Tests for report tier gating via domain ConfidenceAssessment.tier.

Validates the 3-tier certainty system that controls report section visibility:
- Tier A (< 40%): suppress specific diagnoses, show capture guidance
- Tier B (40% ≤ x < 70%): label as hypotheses, verification-only next steps
- Tier C (≥ 70%): full diagnostic behavior with system cards and parts

Tier classification is owned by ``ConfidenceAssessment.tier`` in the domain.
"""

from __future__ import annotations

import pytest

from vibesensor.adapters.pdf.mapping import map_summary, prepare_report_input
from vibesensor.domain import ConfidenceAssessment

# ---------------------------------------------------------------------------
# Unit tests: ConfidenceAssessment.assess().tier domain thresholds
# ---------------------------------------------------------------------------


class TestDomainTierThresholds:
    """Verify domain tier boundaries produce the expected tier."""

    @pytest.mark.parametrize(
        ("confidence", "expected_tier"),
        [
            # Tier A: confidence < 0.40
            pytest.param(0.0, "A", id="zero"),
            pytest.param(0.05, "A", id="5pct"),
            pytest.param(0.10, "A", id="10pct"),
            pytest.param(0.15, "A", id="15pct"),
            pytest.param(0.30, "A", id="30pct"),
            pytest.param(0.39, "A", id="39pct"),
            pytest.param(-0.1, "A", id="negative_edge_case"),
            pytest.param(float("inf"), "A", id="inf_clamps_to_tier_a"),
            pytest.param(float("nan"), "A", id="nan_clamps_to_tier_a"),
            pytest.param(float("-inf"), "A", id="neg_inf_clamps_to_tier_a"),
            # Tier B: 0.40 ≤ confidence < 0.70
            pytest.param(0.40, "B", id="40pct_boundary"),
            pytest.param(0.41, "B", id="41pct"),
            pytest.param(0.50, "B", id="50pct"),
            pytest.param(0.60, "B", id="60pct"),
            pytest.param(0.69, "B", id="69pct"),
            # Tier C: confidence ≥ 0.70
            pytest.param(0.70, "C", id="70pct_boundary"),
            pytest.param(0.75, "C", id="75pct"),
            pytest.param(0.80, "C", id="80pct"),
            pytest.param(0.97, "C", id="97pct"),
            pytest.param(1.0, "C", id="maximum"),
        ],
    )
    def test_tier_classification(self, confidence: float, expected_tier: str) -> None:
        assert ConfidenceAssessment.assess(confidence).tier == expected_tier


# ---------------------------------------------------------------------------
# Helper: minimal summary dict builder
# ---------------------------------------------------------------------------


def _make_summary(
    *,
    confidence: float = 0.06,
    source: str = "wheel/tire",
    location: str = "front_left",
    speed_band: str = "60-70 km/h",
    sensor_count: int = 2,
    lang: str = "en",
    test_plan: list[dict] | None = None,
) -> dict:
    """Build a minimal summary dict for map_summary() testing."""
    finding = {
        "finding_id": "order_1x_wheel",
        "source": source,
        "suspected_source": source,
        "confidence": confidence,
        "strongest_location": location,
        "strongest_speed_band": speed_band,
        "signatures_observed": ["1x wheel"],
    }
    return {
        "findings": [finding],
        "top_causes": [finding],
        "test_plan": test_plan
        or [
            {
                "what": "Inspect wheel balance and radial/lateral runout",
                "why": "Strong wheel order match",
            },
        ],
        "sensor_count_used": sensor_count,
        "lang": lang,
        "metadata": {},
        "report_date": "",
        "record_length": "",
        "start_time_utc": "",
        "end_time_utc": "",
        "warnings": [],
        "sensor_locations": [],
        "sensor_locations_connected_throughout": [],
        "sensor_intensity_by_location": [],
        "most_likely_origin": {},
        "speed_stats": {},
        "run_suitability": [],
        "plots": {},
    }


# ---------------------------------------------------------------------------
# Report output tests: Tier A behavior
# ---------------------------------------------------------------------------


class TestTierAReportOutput:
    """Tier A (low certainty, < 40%): no specific systems, no repair steps."""

    @pytest.fixture
    def tier_a_data(self):
        return map_summary(prepare_report_input(_make_summary(confidence=0.10)))

    def test_tier_a_no_system_cards(self, tier_a_data):
        assert tier_a_data.certainty_tier_key == "A"
        assert tier_a_data.system_cards == []

    def test_tier_a_no_repair_actions(self, tier_a_data):
        for step in tier_a_data.next_steps:
            assert "balance" not in step.action.lower()
            assert "inspect" not in step.action.lower()
            assert "runout" not in step.action.lower()

    def test_tier_a_shows_capture_guidance(self, tier_a_data):
        actions = [s.action for s in tier_a_data.next_steps]
        assert len(actions) >= 3
        assert any("speed sweep" in a.lower() or "speed" in a.lower() for a in actions)
        assert any("sensor" in a.lower() for a in actions)
        assert any("reference" in a.lower() or "tire size" in a.lower() for a in actions)

    def test_tier_a_next_steps_not_empty(self, tier_a_data):
        """The report should not be empty — it must guide the user."""
        assert len(tier_a_data.next_steps) > 0

    def test_tier_a_observed_signature_still_present(self, tier_a_data):
        """Observed signature should still show (pattern data, certainty label)."""
        assert tier_a_data.observed.certainty_label is not None
        assert tier_a_data.observed.certainty_pct is not None


# ---------------------------------------------------------------------------
# Report output tests: Tier B behavior
# ---------------------------------------------------------------------------


class TestTierBReportOutput:
    """Tier B (medium certainty, 40%–70%): hypotheses only, no repair parts."""

    @pytest.fixture
    def tier_b_data(self):
        return map_summary(prepare_report_input(_make_summary(confidence=0.50)))

    def test_tier_b_system_cards_present(self, tier_b_data):
        assert tier_b_data.certainty_tier_key == "B"
        assert len(tier_b_data.system_cards) > 0

    def test_tier_b_cards_labeled_hypothesis(self, tier_b_data):
        for card in tier_b_data.system_cards:
            assert (
                "hypothesis" in card.system_name.lower() or "hypothese" in card.system_name.lower()
            )

    def test_tier_b_no_repair_parts(self, tier_b_data):
        for card in tier_b_data.system_cards:
            assert card.parts == [], f"Tier B cards should have no parts, got {card.parts}"

    def test_tier_b_next_steps_from_test_plan(self, tier_b_data):
        """Tier B should still pass through test_plan steps (verification)."""
        assert len(tier_b_data.next_steps) > 0
        assert tier_b_data.next_steps[0].action != ""


# ---------------------------------------------------------------------------
# Report output tests: Tier C behavior
# ---------------------------------------------------------------------------


class TestTierCReportOutput:
    """Tier C (high certainty, ≥ 70%): full diagnostic behavior."""

    @pytest.fixture
    def tier_c_data(self):
        return map_summary(prepare_report_input(_make_summary(confidence=0.75)))

    def test_tier_c_system_cards_present(self, tier_c_data):
        assert tier_c_data.certainty_tier_key == "C"
        assert len(tier_c_data.system_cards) > 0

    def test_tier_c_cards_have_parts(self, tier_c_data):
        has_parts = any(card.parts for card in tier_c_data.system_cards)
        assert has_parts, "Tier C cards should have repair-oriented parts"

    def test_tier_c_cards_no_hypothesis_label(self, tier_c_data):
        for card in tier_c_data.system_cards:
            assert "hypothesis" not in card.system_name.lower()

    def test_tier_c_next_steps_from_test_plan(self, tier_c_data):
        assert len(tier_c_data.next_steps) > 0


# ---------------------------------------------------------------------------
# Regression test: low certainty scenario
# ---------------------------------------------------------------------------


class TestLowCertaintyRegression:
    """Regression: at low certainty the report must not suggest specific repairs."""

    @pytest.fixture
    def low_cert_data(self):
        return map_summary(prepare_report_input(_make_summary(confidence=0.06)))

    def test_six_percent_certainty_no_parts_to_inspect(self, low_cert_data):
        """With ~6% certainty, no parts inspection should be suggested."""
        for step in low_cert_data.next_steps:
            assert "tire" not in step.action.lower() or "tire size" in step.action.lower()
            assert "bearing" not in step.action.lower()
            assert "mount" not in step.action.lower()

    def test_six_percent_certainty_provides_guidance(self, low_cert_data):
        """With ~6% certainty, guidance on how to improve data quality must be shown."""
        actions_text = " ".join(s.action.lower() for s in low_cert_data.next_steps)
        assert "speed" in actions_text, "Should mention speed sweep guidance"
        assert "sensor" in actions_text, "Should mention sensor coverage guidance"

    def test_baseline_noise_low_certainty(self):
        """Baseline Noise as primary system with low certainty stays in Tier A."""
        data = map_summary(
            prepare_report_input(_make_summary(confidence=0.08, source="baseline_noise"))
        )
        assert data.certainty_tier_key == "A"
        assert data.system_cards == []
        assert len(data.next_steps) >= 3


# ---------------------------------------------------------------------------
# NL language support
# ---------------------------------------------------------------------------


class TestCertaintyTierNL:
    """Verify tier behavior works with Dutch (nl) language."""

    def test_tier_a_nl_capture_guidance(self):
        data = map_summary(prepare_report_input(_make_summary(confidence=0.06, lang="nl")))
        assert data.certainty_tier_key == "A"
        assert len(data.next_steps) >= 3
        actions_text = " ".join(s.action for s in data.next_steps)
        assert "snelheidsvariatie" in actions_text or "sensorlocaties" in actions_text

    def test_tier_b_nl_hypothesis_label(self):
        data = map_summary(prepare_report_input(_make_summary(confidence=0.50, lang="nl")))
        for card in data.system_cards:
            assert (
                "hypothese" in card.system_name.lower() or "hypothesis" in card.system_name.lower()
            )
