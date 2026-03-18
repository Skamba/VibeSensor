from __future__ import annotations

from test_support.findings import make_finding

from vibesensor.domain import OrderMatchObservation
from vibesensor.shared.boundaries.finding import finding_from_payload
from vibesensor.use_cases.diagnostics.findings import (
    collect_order_frequencies,
    finalize_findings,
)


def test_collect_order_frequencies_skips_low_confidence_matches() -> None:
    frequencies = collect_order_frequencies(
        [
            make_finding(
                finding_id="F_ORDER_LOW",
                confidence=0.24,
                matched_points=(
                    OrderMatchObservation(
                        predicted_hz=11.0,
                        matched_hz=11.0,
                        rel_error=0.0,
                        amp=1.0,
                        location="x",
                    ),
                ),
            ),
            finalize_findings(
                [
                    finding_from_payload(
                        {
                            "finding_id": "F_ORDER",
                            "confidence": 0.5,
                            "matched_points": [
                                {
                                    "predicted_hz": 12.0,
                                    "matched_hz": 12.0,
                                    "rel_error": 0.0,
                                    "amp": 1.0,
                                    "location": "x",
                                },
                                {
                                    "predicted_hz": 13.0,
                                    "matched_hz": 13.0,
                                    "rel_error": 0.0,
                                    "amp": 1.0,
                                    "location": "x",
                                },
                            ],
                        }
                    )
                ]
            )[0],
        ],
    )

    assert frequencies == {12.0, 13.0}


def test_finalize_findings_orders_reference_diagnostic_then_info() -> None:
    domain_findings = finalize_findings(
        [
            finding_from_payload(
                {"finding_id": "F_ORDER", "confidence": 0.7, "ranking_score": 2.0}
            ),
            finding_from_payload({"finding_id": "REF_SPEED"}),
            finding_from_payload(
                {
                    "finding_id": "F_PEAK",
                    "severity": "info",
                    "confidence": 0.9,
                    "ranking_score": 5.0,
                }
            ),
        ],
    )

    assert [f.finding_id for f in domain_findings] == ["REF_SPEED", "F001", "F002"]
    assert domain_findings[0].is_reference
    assert domain_findings[1].finding_id == "F001"
    assert domain_findings[2].finding_id == "F002"
