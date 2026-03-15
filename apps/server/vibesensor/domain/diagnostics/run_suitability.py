"""Whether a diagnostic run is trustworthy enough for diagnosis.

``RunSuitability`` aggregates individual data-quality checks into an
overall pass / caution / fail assessment.  Each ``SuitabilityCheck``
records the outcome of one quality gate (e.g. sufficient speed
variation, enough samples, acceptable noise floor).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

__all__ = ["RunSuitability", "SuitabilityCheck"]


def _i18n_ref(key: str, **kwargs: object) -> dict[str, object]:
    return {"_i18n_key": key, **kwargs}


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

    def explanation_i18n_ref(self) -> dict[str, object] | str:
        """Return the i18n reference dict (or empty string) for this check."""
        details = self.details_dict
        if self.check_key == "SUITABILITY_CHECK_SPEED_VARIATION":
            return _i18n_ref(
                "SUITABILITY_SPEED_VARIATION_PASS"
                if self.passed
                else "SUITABILITY_SPEED_VARIATION_WARN",
            )
        if self.check_key == "SUITABILITY_CHECK_SENSOR_COVERAGE":
            return _i18n_ref(
                "SUITABILITY_SENSOR_COVERAGE_PASS"
                if self.passed
                else "SUITABILITY_SENSOR_COVERAGE_WARN",
            )
        if self.check_key == "SUITABILITY_CHECK_REFERENCE_COMPLETENESS":
            return _i18n_ref(
                "SUITABILITY_REFERENCE_COMPLETENESS_PASS"
                if self.passed
                else "SUITABILITY_REFERENCE_COMPLETENESS_WARN",
            )
        if self.check_key == "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS":
            sat_count = int(details.get("sat_count", 0))
            return (
                _i18n_ref("SUITABILITY_SATURATION_PASS")
                if self.passed
                else _i18n_ref("SUITABILITY_SATURATION_WARN", sat_count=sat_count)
            )
        if self.check_key == "SUITABILITY_CHECK_FRAME_INTEGRITY":
            total_dropped = int(details.get("total_dropped", 0))
            total_overflow = int(details.get("total_overflow", 0))
            return (
                _i18n_ref("SUITABILITY_FRAME_INTEGRITY_PASS")
                if self.passed
                else _i18n_ref(
                    "SUITABILITY_FRAME_INTEGRITY_WARN",
                    total_dropped=total_dropped,
                    total_overflow=total_overflow,
                )
            )
        if self.check_key == "SUITABILITY_CHECK_ANALYSIS_SAMPLING":
            stride = str(details.get("stride", ""))
            if stride:
                return _i18n_ref("SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING", stride=stride)
            return ""
        return ""


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
