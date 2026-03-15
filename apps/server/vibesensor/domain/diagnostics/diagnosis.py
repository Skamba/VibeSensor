"""Case-level consolidated conclusion grouping related findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .finding import Finding

if TYPE_CHECKING:
    from .case import DiagnosticCaseEpistemicRule

__all__ = ["Diagnosis"]


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """One consolidated conclusion within a diagnostic case.

    Groups related findings across runs. ``is_actionable`` reflects the
    latest known state via the representative finding (latest-wins
    semantics, not aggregate strength).
    """

    diagnosis_id: str
    source_key: tuple[str, str | None]
    representative_finding: Finding
    epistemic_rule: DiagnosticCaseEpistemicRule
    source_findings: tuple[Finding, ...]

    @property
    def is_actionable(self) -> bool:
        """Delegates to representative finding."""
        return self.representative_finding.is_actionable

    @classmethod
    def from_finding_group(
        cls,
        key: tuple[str, str | None],
        findings: tuple[Finding, ...],
        rule: DiagnosticCaseEpistemicRule,
    ) -> Diagnosis:
        """Build a diagnosis from a group of findings sharing a common identity.

        The representative finding is the last in run order (latest wins).
        """
        if not findings:
            raise ValueError("Diagnosis requires at least one finding")
        source_normalized, location = key
        loc_part = location or "unlocalized"
        diagnosis_id = f"{source_normalized}:{loc_part}"
        return cls(
            diagnosis_id=diagnosis_id,
            source_key=key,
            representative_finding=findings[-1],
            epistemic_rule=rule,
            source_findings=findings,
        )
