from __future__ import annotations

from typing import get_type_hints

from vibesensor.shared.types.finding_payload_parts import (
    FindingCorePayload,
    FindingPayload,
    FindingPresentationPayload,
)


def test_finding_payload_uses_split_core_and_presentation_types() -> None:
    finding_payload_fields = set(get_type_hints(FindingPayload))
    core_fields = set(get_type_hints(FindingCorePayload))
    presentation_fields = set(get_type_hints(FindingPresentationPayload))

    assert {"finding_id", "suspected_source", "evidence_metrics", "frequency_hz"} <= core_fields
    assert {"evidence_summary", "frequency_hz_or_order", "amplitude_metric"} <= presentation_fields
    assert core_fields.isdisjoint(
        {"evidence_summary", "frequency_hz_or_order", "amplitude_metric"},
    )
    assert presentation_fields.isdisjoint({"finding_id", "suspected_source", "evidence_metrics"})
    assert core_fields | presentation_fields == finding_payload_fields
    assert FindingPayload.__required_keys__ == (
        FindingCorePayload.__required_keys__ | FindingPresentationPayload.__required_keys__
    )
