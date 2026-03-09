from __future__ import annotations

from vibesensor.analysis.ranking import group_findings_by_source


def test_group_findings_by_source_preserves_ranked_signatures() -> None:
    grouped = group_findings_by_source(
        [
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.62,
                "frequency_hz_or_order": "2x wheel order",
            },
            {
                "finding_id": "F002",
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.62,
                "frequency_hz_or_order": "1x wheel order",
                "phase_evidence": {"cruise_fraction": 1.0},
            },
            {
                "finding_id": "F003",
                "suspected_source": "engine",
                "confidence_0_to_1": 0.50,
                "frequency_hz_or_order": "2x engine order",
            },
        ],
    )

    assert [rep["suspected_source"] for _score, rep in grouped] == ["wheel/tire", "engine"]
    assert grouped[0][1]["signatures_observed"] == ["1x wheel order", "2x wheel order"]
    assert grouped[0][1]["grouped_count"] == 2
