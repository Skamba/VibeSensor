"""Finding-specific summary serialization helpers."""

from __future__ import annotations

from vibesensor.domain import (
    Finding as DomainFinding,
)
from vibesensor.shared.boundaries.summary_fields.finding import finding_payload_from_domain
from vibesensor.shared.types.finding_payload_parts import FindingPayload


def serialize_findings(findings: tuple[DomainFinding, ...]) -> list[FindingPayload]:
    """Project domain findings into persisted summary payload dictionaries."""
    return [finding_payload_from_domain(finding) for finding in findings]
