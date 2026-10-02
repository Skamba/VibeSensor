"""Finding-specific summary serialization helpers."""

from __future__ import annotations

from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.summary.finding_fields import finding_payload_from_domain
from vibesensor.summary.finding_payload_parts import FindingPayload


def serialize_findings(findings: tuple[DomainFinding, ...]) -> list[FindingPayload]:
    """Project domain findings into persisted summary payload dictionaries."""
    return [finding_payload_from_domain(finding) for finding in findings]
