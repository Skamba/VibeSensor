from __future__ import annotations

from test_support.findings import make_finding_payload

from vibesensor.shared.boundaries.finding import finding_from_payload
from vibesensor.use_cases.diagnostics.top_cause_selection import group_findings_by_source


def test_group_findings_by_source_preserves_ranked_signatures() -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.62,
                "frequency_hz_or_order": "2x wheel order",
            },
            {
                "finding_id": "F002",
                "suspected_source": "wheel/tire",
                "confidence": 0.62,
                "frequency_hz_or_order": "1x wheel order",
                "phase_evidence": {"cruise_fraction": 1.0},
            },
            {
                "finding_id": "F003",
                "suspected_source": "engine",
                "confidence": 0.50,
                "frequency_hz_or_order": "2x engine order",
            },
        ]
    )

    grouped = group_findings_by_source(findings)

    assert [rep.source_normalized for _score, rep in grouped] == ["wheel/tire", "engine"]


def test_group_findings_by_source_keeps_first_tied_member_for_same_location_group() -> None:
    findings = tuple(
        finding_from_payload(payload)
        for payload in [
            make_finding_payload(
                finding_id="F_FRONT_FIRST",
                suspected_source="wheel/tire",
                confidence=0.62,
                strongest_location="front-left wheel",
                frequency_hz_or_order="2x wheel order",
            ),
            make_finding_payload(
                finding_id="F_FRONT_SECOND",
                suspected_source="wheel/tire",
                confidence=0.62,
                strongest_location="front-left wheel",
                frequency_hz_or_order="1x wheel order",
            ),
        ]
    )

    grouped = group_findings_by_source(findings)

    assert len(grouped) == 1
    _score, representative = grouped[0]
    assert representative.finding_id == "F_FRONT_FIRST"
    assert representative.signature_labels == ("2x wheel order", "1x wheel order")


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
