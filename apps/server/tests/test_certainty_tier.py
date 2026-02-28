"""Tests for certainty tier gating logic.

Validates the 3-tier certainty system that controls report section visibility:
- Tier A (≤ 15%): suppress specific diagnoses, show capture guidance
- Tier B (≤ 40%): label as hypotheses, verification-only next steps
- Tier C (> 40%): existing diagnostic behavior
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.report_data_builder import map_summary
from vibesensor.analysis.strength_labels import (
    TIER_A_CEILING,
    TIER_B_CEILING,
    certainty_tier,
)

# ---------------------------------------------------------------------------
# Unit tests: certainty_tier() thresholds and boundary conditions
# ---------------------------------------------------------------------------


class TestCertaintyTierThresholds:
    """Verify tier boundaries are correctly applied."""

    @pytest.mark.parametrize(
        ("confidence", "expected_tier"),
        [
            # Tier A: low confidence (≤ 15%)
            pytest.param(0.0, "A", id="zero"),
            pytest.param(0.05, "A", id="5pct"),
            pytest.param(0.06, "A", id="6pct_screenshot_regression"),
            pytest.param(0.10, "A", id="10pct"),
            pytest.param(TIER_A_CEILING, "A", id="ceiling_a"),
            pytest.param(-0.1, "A", id="negative_edge_case"),
            # Tier B: moderate confidence (15% < x ≤ 40%)
            pytest.param(TIER_A_CEILING + 0.001, "B", id="just_above_a"),
            pytest.param(0.16, "B", id="16pct"),
            pytest.param(0.20, "B", id="20pct"),
            pytest.param(0.30, "B", id="30pct"),
            pytest.param(TIER_B_CEILING, "B", id="ceiling_b"),
            # Tier C: high confidence (> 40%)
            pytest.param(TIER_B_CEILING + 0.001, "C", id="just_above_b"),
            pytest.param(0.41, "C", id="41pct"),
            pytest.param(0.50, "C", id="50pct"),
            pytest.param(0.70, "C", id="70pct"),
            pytest.param(0.80, "C", id="80pct"),
            pytest.param(0.97, "C", id="97pct"),
            pytest.param(1.0, "C", id="maximum"),
        ],
    )
    def test_tier_classification(self, confidence: float, expected_tier: str) -> None:
        assert certainty_tier(confidence) == expected_tier

    def test_tier_a_ceiling_constant(self):
        assert TIER_A_CEILING == 0.15

    def test_tier_b_ceiling_constant(self):
        assert TIER_B_CEILING == 0.40


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
        "confidence_0_to_1": confidence,
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
    }


# ---------------------------------------------------------------------------
# Report output tests: Tier A behavior
# ---------------------------------------------------------------------------


class TestTierAReportOutput:
    """Tier A (very low certainty): no specific systems, no repair steps."""

    def test_tier_a_no_system_cards(self):
        data = map_summary(_make_summary(confidence=0.06))
        assert data.certainty_tier_key == "A"
        assert data.system_cards == []

    def test_tier_a_no_repair_actions(self):
        data = map_summary(_make_summary(confidence=0.06))
        for step in data.next_steps:
            assert "balance" not in step.action.lower()
            assert "inspect" not in step.action.lower()
            assert "runout" not in step.action.lower()

    def test_tier_a_shows_capture_guidance(self):
        data = map_summary(_make_summary(confidence=0.06))
        actions = [s.action for s in data.next_steps]
        assert len(actions) >= 3
        assert any("speed sweep" in a.lower() or "speed" in a.lower() for a in actions)
        assert any("sensor" in a.lower() for a in actions)
        assert any("reference" in a.lower() or "tire size" in a.lower() for a in actions)

    def test_tier_a_at_ceiling(self):
        data = map_summary(_make_summary(confidence=TIER_A_CEILING))
        assert data.certainty_tier_key == "A"
        assert data.system_cards == []

    def test_tier_a_next_steps_not_empty(self):
        """The report should not be empty — it must guide the user."""
        data = map_summary(_make_summary(confidence=0.06))
        assert len(data.next_steps) > 0

    def test_tier_a_observed_signature_still_present(self):
        """Observed signature should still show (pattern data, certainty label)."""
        data = map_summary(_make_summary(confidence=0.06))
        assert data.observed.certainty_label is not None
        assert data.observed.certainty_pct is not None


# ---------------------------------------------------------------------------
# Report output tests: Tier B behavior
# ---------------------------------------------------------------------------


class TestTierBReportOutput:
    """Tier B (guarded certainty): hypotheses only, no repair parts."""

    def test_tier_b_system_cards_present(self):
        data = map_summary(_make_summary(confidence=0.25))
        assert data.certainty_tier_key == "B"
        assert len(data.system_cards) > 0

    def test_tier_b_cards_labeled_hypothesis(self):
        data = map_summary(_make_summary(confidence=0.25))
        for card in data.system_cards:
            assert (
                "hypothesis" in card.system_name.lower() or "hypothese" in card.system_name.lower()
            )

    def test_tier_b_no_repair_parts(self):
        data = map_summary(_make_summary(confidence=0.25))
        for card in data.system_cards:
            assert card.parts == [], f"Tier B cards should have no parts, got {card.parts}"

    def test_tier_b_next_steps_from_test_plan(self):
        """Tier B should still pass through test_plan steps (verification)."""
        data = map_summary(_make_summary(confidence=0.25))
        assert len(data.next_steps) > 0
        assert data.next_steps[0].action != ""


# ---------------------------------------------------------------------------
# Report output tests: Tier C behavior (unchanged)
# ---------------------------------------------------------------------------


class TestTierCReportOutput:
    """Tier C (sufficient certainty): existing diagnostic behavior."""

    def test_tier_c_system_cards_present(self):
        data = map_summary(_make_summary(confidence=0.75))
        assert data.certainty_tier_key == "C"
        assert len(data.system_cards) > 0

    def test_tier_c_cards_have_parts(self):
        data = map_summary(_make_summary(confidence=0.75))
        has_parts = any(card.parts for card in data.system_cards)
        assert has_parts, "Tier C cards should have repair-oriented parts"

    def test_tier_c_cards_no_hypothesis_label(self):
        data = map_summary(_make_summary(confidence=0.75))
        for card in data.system_cards:
            assert "hypothesis" not in card.system_name.lower()

    def test_tier_c_next_steps_from_test_plan(self):
        data = map_summary(_make_summary(confidence=0.75))
        assert len(data.next_steps) > 0


# ---------------------------------------------------------------------------
# Regression test: ~6% certainty scenario
# ---------------------------------------------------------------------------


class TestLowCertaintyRegression:
    """Regression: at ~6% certainty the report must not suggest specific repairs."""

    def test_six_percent_certainty_no_specific_systems(self):
        """With ~6% certainty, the report should NOT list specific systems with findings."""
        data = map_summary(_make_summary(confidence=0.06))
        assert data.system_cards == [], "At 6% certainty, no system finding cards should be shown"

    def test_six_percent_certainty_no_parts_to_inspect(self):
        """With ~6% certainty, no parts inspection should be suggested."""
        data = map_summary(_make_summary(confidence=0.06))
        for step in data.next_steps:
            assert "tire" not in step.action.lower() or "tire size" in step.action.lower()
            assert "bearing" not in step.action.lower()
            assert "mount" not in step.action.lower()

    def test_six_percent_certainty_provides_guidance(self):
        """With ~6% certainty, guidance on how to improve data quality must be shown."""
        data = map_summary(_make_summary(confidence=0.06))
        actions_text = " ".join(s.action.lower() for s in data.next_steps)
        assert "speed" in actions_text, "Should mention speed sweep guidance"
        assert "sensor" in actions_text, "Should mention sensor coverage guidance"

    def test_baseline_noise_low_certainty(self):
        """Baseline Noise as primary system with low certainty stays in Tier A."""
        data = map_summary(_make_summary(confidence=0.08, source="baseline_noise"))
        assert data.certainty_tier_key == "A"
        assert data.system_cards == []
        # Should still provide data-collection guidance
        assert len(data.next_steps) >= 3


# ---------------------------------------------------------------------------
# NL language support
# ---------------------------------------------------------------------------


class TestCertaintyTierNL:
    """Verify tier behavior works with Dutch (nl) language."""

    def test_tier_a_nl_capture_guidance(self):
        data = map_summary(_make_summary(confidence=0.06, lang="nl"))
        assert data.certainty_tier_key == "A"
        assert len(data.next_steps) >= 3
        # Check that NL text is used (not EN)
        actions_text = " ".join(s.action for s in data.next_steps)
        assert "snelheidsvariatie" in actions_text or "sensorlocaties" in actions_text

    def test_tier_b_nl_hypothesis_label(self):
        data = map_summary(_make_summary(confidence=0.25, lang="nl"))
        for card in data.system_cards:
            assert (
                "hypothese" in card.system_name.lower() or "hypothesis" in card.system_name.lower()
            )
