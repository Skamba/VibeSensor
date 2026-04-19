"""Unit tests for pure analysis entry helpers.

Covers:
- Finding.classify_confidence: label/tone/pct_text for 0-1 confidence value
- normalize_lang: minimal language normalisation for summary building
- select_top_causes: grouping, drop-off, max_causes

These functions are exercised indirectly by the full pipeline but were
missing direct unit tests that pin their contracts.
"""

from __future__ import annotations

import math

import pytest
from test_support.findings import make_finding_payload

from vibesensor.domain import Finding
from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload
from vibesensor.use_cases.diagnostics.top_cause_selection import select_top_causes

# ---------------------------------------------------------------------------
# Finding.classify_confidence
# ---------------------------------------------------------------------------


class TestConfidenceLabel:
    """Direct unit tests for Finding.classify_confidence static method."""

    def test_high_threshold_yields_success_tone(self) -> None:
        """Conf >= HIGH_THRESHOLD → CONFIDENCE_HIGH and 'success' tone."""
        label, tone, pct = Finding.classify_confidence(Finding.CONFIDENCE_HIGH_THRESHOLD)
        assert label == "CONFIDENCE_HIGH"
        assert tone == "success"

    def test_medium_threshold_yields_warn_tone(self) -> None:
        """Conf in [MEDIUM, HIGH) → CONFIDENCE_MEDIUM and 'warn' tone."""
        mid = (Finding.CONFIDENCE_MEDIUM_THRESHOLD + Finding.CONFIDENCE_HIGH_THRESHOLD) / 2
        label, tone, _ = Finding.classify_confidence(mid)
        assert label == "CONFIDENCE_MEDIUM"
        assert tone == "warn"

    def test_below_medium_yields_neutral_tone(self) -> None:
        """Conf < MEDIUM_THRESHOLD → CONFIDENCE_LOW and 'neutral' tone."""
        label, tone, _ = Finding.classify_confidence(Finding.CONFIDENCE_MEDIUM_THRESHOLD - 0.01)
        assert label == "CONFIDENCE_LOW"
        assert tone == "neutral"

    def test_zero_input_returns_low(self) -> None:
        """Zero confidence → CONFIDENCE_LOW."""
        label, tone, pct = Finding.classify_confidence(0.0)
        assert label == "CONFIDENCE_LOW"
        assert pct == "0%"

    def test_pct_text_format_is_integer_percent(self) -> None:
        """pct_text should be e.g. '82%', not '0.82%' or '82.0%'."""
        _, _, pct = Finding.classify_confidence(0.82)
        assert pct == "82%"

    def test_pct_text_clamps_to_100(self) -> None:
        """Values > 1.0 should yield '100%', not '150%'."""
        _, _, pct = Finding.classify_confidence(1.5)
        assert pct == "100%"

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            pytest.param(float("nan"), ("CONFIDENCE_LOW", "neutral", "0%"), id="nan"),
            pytest.param(-0.20, ("CONFIDENCE_LOW", "neutral", "0%"), id="negative"),
            pytest.param(math.inf, ("CONFIDENCE_LOW", "neutral", "0%"), id="infinite"),
            pytest.param(1.50, ("CONFIDENCE_HIGH", "success", "100%"), id="above-one"),
        ],
    )
    def test_invalid_and_out_of_range_inputs_follow_clamped_confidence_semantics(
        self,
        confidence: float,
        expected: tuple[str, str, str],
    ) -> None:
        assert Finding.classify_confidence(confidence) == expected

    def test_negligible_band_caps_high_to_medium(self) -> None:
        """strength_band_key='negligible' must reduce HIGH → MEDIUM."""
        label, tone, _ = Finding.classify_confidence(
            Finding.CONFIDENCE_HIGH_THRESHOLD + 0.05,
            strength_band_key="negligible",
        )
        assert label == "CONFIDENCE_MEDIUM"
        assert tone == "warn"

    def test_negligible_band_does_not_affect_medium(self) -> None:
        """strength_band_key='negligible' only caps HIGH, not MEDIUM already."""
        mid = (Finding.CONFIDENCE_MEDIUM_THRESHOLD + Finding.CONFIDENCE_HIGH_THRESHOLD) / 2
        label, tone, _ = Finding.classify_confidence(mid, strength_band_key="negligible")
        assert label == "CONFIDENCE_MEDIUM"

    def test_non_negligible_band_leaves_high_intact(self) -> None:
        """An unrelated band key must not suppress a HIGH label."""
        label, tone, _ = Finding.classify_confidence(
            Finding.CONFIDENCE_HIGH_THRESHOLD + 0.05,
            strength_band_key="strong",
        )
        assert label == "CONFIDENCE_HIGH"


# ---------------------------------------------------------------------------
# select_top_causes
# ---------------------------------------------------------------------------


class TestSelectTopCauses:
    """Direct unit tests for select_top_causes grouping and drop-off."""

    @staticmethod
    def _to_domain(*payloads: dict[str, object]) -> tuple[Finding, ...]:
        return tuple(finding_from_payload(p) for p in payloads)

    def test_empty_findings_returns_empty(self) -> None:
        domain_findings = select_top_causes(())
        assert domain_findings == ()

    def test_below_min_confidence_findings_excluded(self) -> None:
        """Findings below ORDER_MIN_CONFIDENCE (0.25) must be filtered."""
        findings = self._to_domain(
            make_finding_payload(suspected_source="wheel/tire", confidence=0.10),
        )
        domain_findings = select_top_causes(findings)
        assert domain_findings == ()

    def test_info_severity_excluded(self) -> None:
        """Info-severity findings must not appear in top causes."""
        findings = self._to_domain(
            make_finding_payload(suspected_source="wheel/tire", confidence=0.90, severity="info"),
        )
        domain_findings = select_top_causes(findings)
        assert domain_findings == ()

    def test_ref_finding_excluded(self) -> None:
        """Findings whose ID starts with REF_ must be excluded."""
        findings = self._to_domain(
            make_finding_payload(
                suspected_source="baseline",
                confidence=0.95,
                finding_id="REF_BASELINE",
            ),
        )
        domain_findings = select_top_causes(findings)
        assert domain_findings == ()

    def test_respects_max_causes_limit(self) -> None:
        findings = self._to_domain(
            make_finding_payload(
                finding_id="F_WHEEL",
                suspected_source="wheel/tire",
                confidence=0.90,
            ),
            make_finding_payload(
                finding_id="F_DRIVELINE",
                suspected_source="driveline",
                confidence=0.85,
            ),
            make_finding_payload(
                finding_id="F_ENGINE",
                suspected_source="engine",
                confidence=0.80,
            ),
            make_finding_payload(
                finding_id="F_BODY",
                suspected_source="body resonance",
                confidence=0.75,
            ),
        )
        domain_findings = select_top_causes(findings, max_causes=2)
        assert [finding.finding_id for finding in domain_findings] == ["F_WHEEL", "F_DRIVELINE"]
        assert {finding.finding_id for finding in findings} - {
            finding.finding_id for finding in domain_findings
        } == {"F_ENGINE", "F_BODY"}

    def test_best_per_source_group_selected(self) -> None:
        findings = self._to_domain(
            make_finding_payload(
                finding_id="F_WHEEL_BEST",
                suspected_source="wheel/tire",
                confidence=0.90,
                frequency_hz_or_order="2x wheel order",
            ),
            make_finding_payload(
                finding_id="F_WHEEL_WEAKER",
                suspected_source="wheel/tire",
                confidence=0.60,
                frequency_hz_or_order="1x wheel order",
            ),
            make_finding_payload(
                finding_id="F_ENGINE",
                suspected_source="engine",
                confidence=0.80,
            ),
        )
        domain_findings = select_top_causes(findings, max_causes=3)
        assert [finding.finding_id for finding in domain_findings] == ["F_WHEEL_BEST", "F_ENGINE"]
        best_wheel = domain_findings[0]
        assert best_wheel.source_normalized == "wheel/tire"
        assert best_wheel.confidence == pytest.approx(0.90)
        assert best_wheel.signature_labels == ("2x wheel order", "1x wheel order")

    def test_drop_off_threshold_excludes_low_scoring_groups_even_below_max_causes(self) -> None:
        findings = self._to_domain(
            make_finding_payload(
                finding_id="F_TOP",
                suspected_source="wheel/tire",
                confidence=0.90,
            ),
            make_finding_payload(
                finding_id="F_CLOSE",
                suspected_source="engine",
                confidence=0.79,
            ),
            make_finding_payload(
                finding_id="F_BELOW",
                suspected_source="body resonance",
                confidence=0.60,
            ),
        )
        domain_findings = select_top_causes(findings, max_causes=3)

        assert [finding.finding_id for finding in domain_findings] == ["F_TOP", "F_CLOSE"]
        assert all(isinstance(finding, Finding) for finding in domain_findings)

    def test_equal_score_groups_keep_first_seen_source_order(self) -> None:
        findings = self._to_domain(
            make_finding_payload(
                finding_id="F_WHEEL",
                suspected_source="wheel/tire",
                confidence=0.80,
                strongest_location="front-left wheel",
            ),
            make_finding_payload(
                finding_id="F_ENGINE",
                suspected_source="engine",
                confidence=0.80,
            ),
            make_finding_payload(
                finding_id="F_DRIVELINE",
                suspected_source="driveline",
                confidence=0.50,
            ),
        )

        domain_findings = select_top_causes(findings, max_causes=2)

        assert [finding.finding_id for finding in domain_findings] == ["F_WHEEL", "F_ENGINE"]

    def test_wheel_driveline_overlap_adds_explicit_reason_when_both_surface(self) -> None:
        wheel = finding_from_payload(
            make_finding_payload(
                finding_id="F_WHEEL",
                suspected_source="wheel/tire",
                confidence=0.66,
                strongest_location="front-left",
            ),
        ).with_confidence_assessment(
            strength_band_key="moderate",
            steady_speed=True,
            has_reference_gaps=False,
            sensor_count=4,
        )
        driveline = finding_from_payload(
            make_finding_payload(
                finding_id="F_DRIVELINE",
                suspected_source="driveline",
                confidence=0.61,
                strongest_location="front-left",
            ),
        ).with_confidence_assessment(
            strength_band_key="moderate",
            steady_speed=True,
            has_reference_gaps=False,
            sensor_count=4,
        )

        domain_findings = select_top_causes((wheel, driveline))

        assert [finding.finding_id for finding in domain_findings] == [
            "F_WHEEL",
            "F_DRIVELINE",
        ]
        for finding in domain_findings:
            assert finding.confidence_assessment is not None
            reason = finding.confidence_assessment.reason.lower()
            assert "wheel and driveline evidence overlap" in reason
            assert "could not strongly differentiate" in reason
            assert "inspect both areas" in reason
