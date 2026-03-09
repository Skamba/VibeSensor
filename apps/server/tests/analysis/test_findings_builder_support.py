from __future__ import annotations

from vibesensor.analysis.findings.builder_support import (
    collect_order_frequencies,
    finalize_findings,
)


def test_collect_order_frequencies_skips_low_confidence_matches() -> None:
    frequencies = collect_order_frequencies(
        [
            {
                "confidence_0_to_1": 0.24,
                "matched_points": [{"matched_hz": 11.0}],
            },
            {
                "confidence_0_to_1": 0.5,
                "matched_points": [{"matched_hz": 12.0}, {"matched_hz": 13.0}],
            },
        ],
    )

    assert frequencies == {12.0, 13.0}


def test_finalize_findings_orders_reference_diagnostic_then_info() -> None:
    findings = finalize_findings(
        [
            {"finding_id": "F_ORDER", "confidence_0_to_1": 0.7, "_ranking_score": 2.0},
            {"finding_id": "REF_SPEED"},
            {
                "finding_id": "F_PEAK",
                "severity": "info",
                "confidence_0_to_1": 0.9,
                "_ranking_score": 5.0,
            },
        ],
    )

    assert [finding["finding_id"] for finding in findings] == ["REF_SPEED", "F001", "F002"]
    assert findings[1]["_ranking_score"] == 2.0
    assert findings[2]["severity"] == "info"
