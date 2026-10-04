"""Top causes: findings grouped per source (one per wheel corner), trimmed by score drop-off."""

from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload

from vibesensor.analysis.top_cause_selection import group_findings_by_source, select_top_causes
from vibesensor.domain.finding import Finding
from vibesensor.summary.finding_fields import finding_from_payload


class TestSelectTopCauses:
    """Direct unit tests for select_top_causes grouping and drop-off."""

    @staticmethod
    def _to_domain(*payloads: dict[str, object]) -> tuple[Finding, ...]:
        return tuple(finding_from_payload(p) for p in payloads)

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


def test_group_findings_by_source_keeps_tied_wheel_locations_separate_in_input_order() -> None:
    findings = tuple(
        finding_from_payload(payload)
        for payload in [
            make_finding_payload(
                finding_id="F_FRONT_LEFT",
                suspected_source="wheel/tire",
                confidence=0.62,
                strongest_location="front-left wheel",
            ),
            make_finding_payload(
                finding_id="F_FRONT_RIGHT",
                suspected_source="wheel/tire",
                confidence=0.62,
                strongest_location="front-right wheel",
            ),
            make_finding_payload(
                finding_id="F_ENGINE",
                suspected_source="engine",
                confidence=0.50,
            ),
        ]
    )

    grouped = group_findings_by_source(findings)

    assert [rep.finding_id for _score, rep in grouped] == [
        "F_FRONT_LEFT",
        "F_FRONT_RIGHT",
        "F_ENGINE",
    ]
