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

    @pytest.mark.parametrize(
        ("confidence", "strength_band_key", "expected"),
        [
            pytest.param(
                Finding.CONFIDENCE_HIGH_THRESHOLD,
                None,
                ("CONFIDENCE_HIGH", "success", "70%"),
                id="high-threshold",
            ),
            pytest.param(
                (Finding.CONFIDENCE_MEDIUM_THRESHOLD + Finding.CONFIDENCE_HIGH_THRESHOLD) / 2,
                None,
                ("CONFIDENCE_MEDIUM", "warn", "55%"),
                id="medium-band",
            ),
            pytest.param(
                Finding.CONFIDENCE_MEDIUM_THRESHOLD - 0.01,
                None,
                ("CONFIDENCE_LOW", "neutral", "39%"),
                id="below-medium",
            ),
            pytest.param(0.0, None, ("CONFIDENCE_LOW", "neutral", "0%"), id="zero"),
            pytest.param(0.82, None, ("CONFIDENCE_HIGH", "success", "82%"), id="integer-pct"),
            pytest.param(float("nan"), None, ("CONFIDENCE_LOW", "neutral", "0%"), id="nan"),
            pytest.param(-0.20, None, ("CONFIDENCE_LOW", "neutral", "0%"), id="negative"),
            pytest.param(math.inf, None, ("CONFIDENCE_LOW", "neutral", "0%"), id="infinite"),
            pytest.param(1.50, None, ("CONFIDENCE_HIGH", "success", "100%"), id="above-one"),
            pytest.param(
                Finding.CONFIDENCE_HIGH_THRESHOLD + 0.05,
                "negligible",
                ("CONFIDENCE_MEDIUM", "warn", "75%"),
                id="negligible-caps-high",
            ),
            pytest.param(
                (Finding.CONFIDENCE_MEDIUM_THRESHOLD + Finding.CONFIDENCE_HIGH_THRESHOLD) / 2,
                "negligible",
                ("CONFIDENCE_MEDIUM", "warn", "55%"),
                id="negligible-keeps-medium",
            ),
            pytest.param(
                Finding.CONFIDENCE_HIGH_THRESHOLD + 0.05,
                "strong",
                ("CONFIDENCE_HIGH", "success", "75%"),
                id="other-band-keeps-high",
            ),
        ],
    )
    def test_classify_confidence_cases(
        self,
        confidence: float,
        strength_band_key: str | None,
        expected: tuple[str, str, str],
    ) -> None:
        assert (
            Finding.classify_confidence(
                confidence,
                strength_band_key=strength_band_key,
            )
            == expected
        )


class TestSelectTopCauses:
    """Direct unit tests for select_top_causes grouping and drop-off."""

    @staticmethod
    def _to_domain(*payloads: dict[str, object]) -> tuple[Finding, ...]:
        return tuple(finding_from_payload(p) for p in payloads)

    @pytest.mark.parametrize(
        ("findings", "expected_ids"),
        [
            pytest.param((), (), id="empty"),
            pytest.param(
                (
                    make_finding_payload(
                        suspected_source="wheel/tire",
                        confidence=0.10,
                    ),
                ),
                (),
                id="below-min-confidence",
            ),
            pytest.param(
                (
                    make_finding_payload(
                        suspected_source="wheel/tire",
                        confidence=0.90,
                        severity="info",
                    ),
                ),
                (),
                id="info-severity",
            ),
            pytest.param(
                (
                    make_finding_payload(
                        suspected_source="baseline",
                        confidence=0.95,
                        finding_id="REF_BASELINE",
                    ),
                ),
                (),
                id="reference-finding",
            ),
            pytest.param(
                (
                    make_finding_payload(
                        finding_id="F_VALID",
                        suspected_source="wheel/tire",
                        confidence=0.70,
                    ),
                ),
                ("F_VALID",),
                id="returns-domain-findings",
            ),
        ],
    )
    def test_select_top_causes_filters_and_returns_findings(
        self,
        findings: tuple[dict[str, object], ...],
        expected_ids: tuple[str, ...],
    ) -> None:
        domain_findings = select_top_causes(self._to_domain(*findings))

        assert isinstance(domain_findings, tuple)
        assert all(isinstance(finding, Finding) for finding in domain_findings)
        assert tuple(finding.finding_id for finding in domain_findings) == expected_ids

    @pytest.mark.parametrize(
        ("findings", "max_causes", "expected_ids", "expected_first_signatures"),
        [
            pytest.param(
                (
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
                ),
                2,
                ("F_WHEEL", "F_DRIVELINE"),
                None,
                id="max-causes-limit",
            ),
            pytest.param(
                (
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
                ),
                3,
                ("F_WHEEL_BEST", "F_ENGINE"),
                ("2x wheel order", "1x wheel order"),
                id="best-per-source-group",
            ),
            pytest.param(
                (
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
                ),
                3,
                ("F_TOP", "F_CLOSE"),
                None,
                id="drop-off-threshold",
            ),
            pytest.param(
                (
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
                ),
                2,
                ("F_WHEEL", "F_ENGINE"),
                None,
                id="equal-score-keeps-source-order",
            ),
        ],
    )
    def test_select_top_causes_selection_cases(
        self,
        findings: tuple[dict[str, object], ...],
        max_causes: int,
        expected_ids: tuple[str, ...],
        expected_first_signatures: tuple[str, ...] | None,
    ) -> None:
        domain_findings = select_top_causes(
            self._to_domain(*findings),
            max_causes=max_causes,
        )
        assert tuple(finding.finding_id for finding in domain_findings) == expected_ids
        if expected_first_signatures is not None:
            assert domain_findings[0].signature_labels == expected_first_signatures
            assert domain_findings[0].confidence == pytest.approx(0.90)
            assert domain_findings[0].source_normalized == "wheel/tire"

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
