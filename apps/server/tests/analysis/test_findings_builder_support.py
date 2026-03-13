from __future__ import annotations

from vibesensor.analysis.findings import (
    collect_order_frequencies,
    finalize_findings,
)


def test_collect_order_frequencies_skips_low_confidence_matches() -> None:
    frequencies = collect_order_frequencies(
        [
            {
                "confidence": 0.24,
                "matched_points": [{"matched_hz": 11.0}],
            },
            {
                "confidence": 0.5,
                "matched_points": [{"matched_hz": 12.0}, {"matched_hz": 13.0}],
            },
        ],
    )

    assert frequencies == {12.0, 13.0}


def test_finalize_findings_orders_reference_diagnostic_then_info() -> None:
    findings, domain_findings = finalize_findings(
        [
            {"finding_id": "F_ORDER", "confidence": 0.7, "ranking_score": 2.0},
            {"finding_id": "REF_SPEED"},
            {
                "finding_id": "F_PEAK",
                "severity": "info",
                "confidence": 0.9,
                "ranking_score": 5.0,
            },
        ],
    )

    assert [finding["finding_id"] for finding in findings] == ["REF_SPEED", "F001", "F002"]
    assert findings[1]["ranking_score"] == 2.0
    assert findings[2]["severity"] == "info"
    # Domain objects match payloads
    assert len(domain_findings) == 3
    assert domain_findings[0].is_reference
    assert domain_findings[1].finding_id == "F001"
    assert domain_findings[2].finding_id == "F002"
