from __future__ import annotations

from typing import get_type_hints

from vibesensor.shared.types.finding_payload_parts import (
    FindingCorePayload,
    FindingPresentationPayload,
)
from vibesensor.shared.types.history_analysis_contracts import FindingPayload


def test_finding_payload_part_types_keep_core_and_presentation_split() -> None:
    finding_payload_fields = set(get_type_hints(FindingPayload))
    core_fields = set(get_type_hints(FindingCorePayload))
    presentation_fields = set(get_type_hints(FindingPresentationPayload))

    assert {"finding_id", "suspected_source", "evidence_metrics"} <= core_fields
    assert {"evidence_summary", "frequency_hz_or_order", "amplitude_metric"} <= presentation_fields
    assert core_fields.isdisjoint(
        {"evidence_summary", "frequency_hz_or_order", "amplitude_metric"},
    )
    assert presentation_fields.isdisjoint({"finding_id", "suspected_source", "evidence_metrics"})
    assert core_fields | presentation_fields <= finding_payload_fields
