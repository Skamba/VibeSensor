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
            if self.passed:
                return _i18n_ref("SUITABILITY_SPEED_VARIATION_PASS")
            if details.get("manual_speed"):
                return _i18n_ref("SUITABILITY_SPEED_VARIATION_MANUAL", manual_speed=1)
            if details.get("steady_speed"):
                return _i18n_ref("SUITABILITY_SPEED_VARIATION_STEADY", steady_speed=1)
            return _i18n_ref("SUITABILITY_SPEED_VARIATION_WARN")
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
            frames_lost = total_dropped + total_overflow > 0
            if not self.passed and details.get("replay_incomplete") and not frames_lost:
                return _i18n_ref("SUITABILITY_FRAME_INTEGRITY_REPLAY_WARN", **details)
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
        if self.check_key == "SUITABILITY_CHECK_RUN_DURATION":
            raw_samples = int(details.get("raw_samples", 0))
            required_raw_samples = int(details.get("required_raw_samples", 0))
            if required_raw_samples > 0:
                return _i18n_ref(
                    "SUITABILITY_RAW_SAMPLE_DURATION_WARNING",
                    raw_samples=raw_samples,
                    required_raw_samples=required_raw_samples,
                )
            summary_rows = int(details.get("summary_rows", 0))
            required_summary_rows = int(details.get("required_summary_rows", 0))
            if required_summary_rows > 0:
                return _i18n_ref(
                    "SUITABILITY_SUMMARY_ROW_COUNT_WARNING",
                    summary_rows=summary_rows,
                    required_summary_rows=required_summary_rows,
                )
            return _i18n_ref("SUITABILITY_RUN_DURATION_WARNING")
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

    @property
    def has_reference_gaps(self) -> bool:
        """Whether reference data is incomplete for this run."""
        return any(
            c.check_key == "SUITABILITY_CHECK_REFERENCE_COMPLETENESS" and not c.passed
            for c in self.checks
        )

    _REPLAY_COVERAGE_KEYS: ClassVar[tuple[str, ...]] = (
        "replay_partial",
        "replay_missing",
        "replay_gaps",
        "replay_overlaps",
    )

    def with_incomplete_raw_replay(
        self, *, partial: int, missing: int, gaps: int, overlaps: int
    ) -> RunSuitability:
        """Fail the frame-integrity check when the raw capture did not cover the run.

        Those moments were analysed from the stored summaries, so the report must
        not also say that no sensor data was lost.
        """
        key = "SUITABILITY_CHECK_FRAME_INTEGRITY"
        counts = (partial, missing, gaps, overlaps)
        checks = tuple(
            SuitabilityCheck(
                check_key=key,
                state="warn",
                details=(
                    *(item for item in check.details if not item[0].startswith("replay_")),
                    ("replay_incomplete", 1),
                    *zip(self._REPLAY_COVERAGE_KEYS, (max(0, n) for n in counts), strict=True),
                ),
            )
            if check.check_key == key
            else check
            for check in self.checks
        )
        return RunSuitability(checks=checks)

    @staticmethod
    def _speed_variation(
        *, steady_speed: bool, speed_sufficient: bool, manual_speed: bool
    ) -> SuitabilityCheck:
        key = "SUITABILITY_CHECK_SPEED_VARIATION"
        if not speed_sufficient:
            return SuitabilityCheck(check_key=key, state="warn")
        if manual_speed:
            return SuitabilityCheck(check_key=key, state="warn", details=(("manual_speed", 1),))
        if steady_speed:
            return SuitabilityCheck(check_key=key, state="warn", details=(("steady_speed", 1),))
        return SuitabilityCheck(check_key=key, state="pass")

    @classmethod
    def evaluate(
        cls,
        *,
        steady_speed: bool,
        speed_sufficient: bool,
        manual_speed: bool,
        sensor_count: int,
        reference_complete: bool,
        sat_count: int,
        total_dropped: int,
        total_overflow: int,
    ) -> RunSuitability:
        """Evaluate run suitability from typed analysis inputs.

        Orders are told apart by how their frequency follows the speed, so the
        speed check passes only for a live speed that varied: not for a speed
        typed in by hand, nor for one held nearly constant.
        """
        frame_issues = total_dropped + total_overflow
        return cls(
            checks=(
                cls._speed_variation(
                    steady_speed=steady_speed,
                    speed_sufficient=speed_sufficient,
                    manual_speed=manual_speed,
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
