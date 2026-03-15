from __future__ import annotations

from vibesensor.use_cases.diagnostics.top_cause_selection import group_findings_by_source
from vibesensor.shared.boundaries.finding import finding_from_payload


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
