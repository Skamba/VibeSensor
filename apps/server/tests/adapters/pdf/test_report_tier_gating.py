"""Tests for report tier gating via domain ConfidenceAssessment.tier.

Validates the 3-tier certainty system that controls report section visibility:
- Tier A (< 40%): suppress specific diagnoses, show capture guidance
- Tier B (40% ≤ x < 70%): label as hypotheses, verification-only next steps
- Tier C (≥ 70%): full diagnostic behavior with system cards and parts

Tier classification is owned by ``ConfidenceAssessment.tier`` in the domain.
"""

from __future__ import annotations

import pytest

from vibesensor.domain import ConfidenceAssessment
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document

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
    test_plan: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build a minimal summary dict for build_report_document() testing."""
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


def _build_report_data(**kwargs: object):
    return build_report_document(prepare_report_input(_make_summary(**kwargs)))


class TestTierReportOutput:
    """Tier A/B/C report behavior should follow semantic gating rules."""

    @pytest.mark.parametrize(
        ("confidence", "expected_tier", "lang", "expect_status_label", "expect_parts"),
        [
            pytest.param(0.10, "A", "en", False, False, id="tier-a-en"),
            pytest.param(0.06, "A", "nl", False, False, id="tier-a-nl"),
            pytest.param(0.50, "B", "en", True, False, id="tier-b-en"),
            pytest.param(0.50, "B", "nl", True, False, id="tier-b-nl"),
            pytest.param(0.75, "C", "en", False, True, id="tier-c-en"),
        ],
    )
    def test_tier_gating_contracts(
        self,
        confidence: float,
        expected_tier: str,
        lang: str,
        expect_status_label: bool,
        expect_parts: bool,
    ) -> None:
        data = _build_report_data(confidence=confidence, lang=lang)

        assert data.certainty_tier_key == expected_tier
        assert data.observed.certainty_label is not None
        assert data.observed.certainty_pct is not None

        if expected_tier == "A":
            assert data.system_cards == []
            assert len(data.next_steps) == 3
            assert all(step.confirm is None for step in data.next_steps)
            assert all(step.falsify is None for step in data.next_steps)
            assert {step.action for step in data.next_steps} != {
                "Inspect wheel balance and radial/lateral runout"
            }
            return

        assert len(data.system_cards) == 1
        assert [step.action for step in data.next_steps] == [
            "Inspect wheel balance and radial/lateral runout"
        ]

        card = data.system_cards[0]
        assert card.system_name
        assert card.strongest_location == "front_left"
        assert bool(card.status_label) is expect_status_label
        assert bool(card.parts) is expect_parts
        if expect_status_label:
            assert card.status_label not in {"", None}
            assert card.parts == []
        else:
            assert card.status_label is None
            assert [part.name for part in card.parts] == [
                "Tire flat spot / out-of-round",
                "Wheel balance weights",
                "Wheel hub bearing",
            ]

    @pytest.mark.parametrize(
        ("confidence", "expected_tier"),
        [
            pytest.param(0.06, "A", id="tier-a"),
            pytest.param(0.50, "B", id="tier-b"),
            pytest.param(0.75, "C", id="tier-c"),
        ],
    )
    def test_dutch_localization_preserves_same_tier_semantics(
        self,
        confidence: float,
        expected_tier: str,
    ) -> None:
        english = _build_report_data(confidence=confidence, lang="en")
        dutch = _build_report_data(confidence=confidence, lang="nl")

        assert english.certainty_tier_key == dutch.certainty_tier_key == expected_tier
        assert len(english.system_cards) == len(dutch.system_cards)
        assert len(english.next_steps) == len(dutch.next_steps)

        if expected_tier == "A":
            assert english.system_cards == dutch.system_cards == []
            assert [step.action for step in english.next_steps] != [
                step.action for step in dutch.next_steps
            ]
            return

        english_card = english.system_cards[0]
        dutch_card = dutch.system_cards[0]
        assert english_card.system_name
        assert dutch_card.system_name
        assert english_card.system_name != dutch_card.system_name
        assert english_card.strongest_location == dutch_card.strongest_location == "front_left"
        assert bool(english_card.parts) is bool(dutch_card.parts)
        assert (english_card.status_label is None) is (dutch_card.status_label is None)
        if english_card.status_label is not None:
            assert dutch_card.status_label not in {"", None, english_card.status_label}

    def test_baseline_noise_low_certainty_stays_capture_guidance_only(self) -> None:
        data = _build_report_data(confidence=0.08, source="baseline_noise")

        assert data.certainty_tier_key == "A"
        assert data.system_cards == []
        assert len(data.next_steps) == 3
