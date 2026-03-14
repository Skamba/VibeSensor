"""Whether a diagnostic run is trustworthy enough for diagnosis.

``RunSuitability`` aggregates individual data-quality checks into an
overall pass / caution / fail assessment.  Each ``SuitabilityCheck``
records the outcome of one quality gate (e.g. sufficient speed
variation, enough samples, acceptable noise floor).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RunSuitability", "SuitabilityCheck"]


@dataclass(frozen=True, slots=True)
class SuitabilityCheck:
    """One data-quality check result."""

    check_key: str
    state: str  # "pass", "warn", "fail"
    explanation: str = ""

    @property
    def passed(self) -> bool:
        return self.state == "pass"

    @property
    def failed(self) -> bool:
        return self.state == "fail"

    @property
    def is_warning(self) -> bool:
        return self.state == "warn"


@dataclass(frozen=True, slots=True)
class RunSuitability:
    """Whether a run is trustworthy enough for diagnosis."""

    checks: tuple[SuitabilityCheck, ...] = ()

    # -- domain queries ----------------------------------------------------

    @property
    def overall(self) -> str:
        """Aggregate assessment: ``'pass'``, ``'caution'``, or ``'fail'``."""
        if any(c.failed for c in self.checks):
            return "fail"
        if any(c.is_warning for c in self.checks):
            return "caution"
        return "pass"

    @property
    def is_usable(self) -> bool:
        """Whether the run is trustworthy enough to draw conclusions from."""
        return self.overall != "fail"

    @property
    def has_warnings(self) -> bool:
        return any(c.is_warning for c in self.checks)

    @property
    def failed_checks(self) -> tuple[SuitabilityCheck, ...]:
        return tuple(c for c in self.checks if c.failed)

    @property
    def warning_checks(self) -> tuple[SuitabilityCheck, ...]:
        return tuple(c for c in self.checks if c.is_warning)

    # -- boundary adapter --------------------------------------------------

    @staticmethod
    def from_checks(checks: list[dict[str, object]]) -> RunSuitability:
        """Construct from a list of ``RunSuitabilityCheck`` dicts (boundary adapter)."""
        domain_checks = tuple(
            SuitabilityCheck(
                check_key=str(c.get("check_key", c.get("check", ""))),
                state=str(c.get("state", "pass")),
                explanation=str(c.get("explanation", "")),
            )
            for c in checks
            if isinstance(c, dict)
        )
        return RunSuitability(checks=domain_checks)
