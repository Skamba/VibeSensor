"""Whether a diagnostic run is trustworthy enough for diagnosis.

``RunSuitability`` aggregates individual data-quality checks into an
overall pass / caution / fail assessment.  Each ``SuitabilityCheck``
records the outcome of one quality gate (e.g. sufficient speed
variation, enough samples, acceptable noise floor).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

__all__ = ["RunSuitability", "SuitabilityCheck"]


@dataclass(frozen=True, slots=True)
class SuitabilityCheck:
    """One data-quality check result."""

    check_key: str
    state: str  # "pass", "warn", "fail"
    details: tuple[tuple[str, int], ...] = ()

    @property
    def passed(self) -> bool:
        return self.state == "pass"

    @property
    def failed(self) -> bool:
        return self.state == "fail"

    @property
    def is_warning(self) -> bool:
        return self.state == "warn"

    @property
    def details_dict(self) -> dict[str, int]:
        return dict(self.details)


@dataclass(frozen=True, slots=True)
class RunSuitability:
    """Whether a run is trustworthy enough for diagnosis."""

    checks: tuple[SuitabilityCheck, ...] = ()

    _MIN_SENSOR_COUNT: ClassVar[int] = 3

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

    @classmethod
    def evaluate(
        cls,
        *,
        steady_speed: bool,
        speed_sufficient: bool,
        sensor_count: int,
        reference_complete: bool,
        sat_count: int,
        total_dropped: int,
        total_overflow: int,
    ) -> RunSuitability:
        """Evaluate run suitability from typed analysis inputs."""
        speed_variation_ok = speed_sufficient and not steady_speed
        frame_issues = total_dropped + total_overflow
        return cls(
            checks=(
                SuitabilityCheck(
                    check_key="SUITABILITY_CHECK_SPEED_VARIATION",
                    state="pass" if speed_variation_ok else "warn",
                ),
                SuitabilityCheck(
                    check_key="SUITABILITY_CHECK_SENSOR_COVERAGE",
                    state="pass" if sensor_count >= cls._MIN_SENSOR_COUNT else "warn",
                ),
                SuitabilityCheck(
                    check_key="SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                    state="pass" if reference_complete else "warn",
                ),
                SuitabilityCheck(
                    check_key="SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                    state="pass" if sat_count == 0 else "warn",
                    details=(("sat_count", sat_count),),
                ),
                SuitabilityCheck(
                    check_key="SUITABILITY_CHECK_FRAME_INTEGRITY",
                    state="pass" if frame_issues == 0 else "warn",
                    details=(
                        ("total_dropped", total_dropped),
                        ("total_overflow", total_overflow),
                    ),
                ),
            )
        )

    # -- boundary adapter --------------------------------------------------

    @staticmethod
    def from_checks(checks: Sequence[Mapping[str, object]]) -> RunSuitability:
        """Construct from a list of ``RunSuitabilityCheck`` dicts (boundary adapter)."""
        domain_checks = tuple(
            SuitabilityCheck(
                check_key=str(c.get("check_key", c.get("check", ""))),
                state=str(c.get("state", "pass")),
            )
            for c in checks
            if isinstance(c, Mapping)
        )
        return RunSuitability(checks=domain_checks)
