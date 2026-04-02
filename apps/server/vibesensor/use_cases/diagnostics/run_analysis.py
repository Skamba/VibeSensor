"""Typed diagnostics analysis entrypoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

from ._analysis_models import FindingsBuilder
from ._analysis_result import AnalysisResult
from ._run_input import DiagnosticsRunInput, build_diagnostics_run_input
from ._types import AccelStatistics
from ._validation import _validate_required_strength_metrics
from .analysis_pipeline import (
    build_findings_for_typed_samples,
    execute_analysis,
)
from .run_data_preparation import PreparedRunData, prepare_run_data
from .statistics import compute_accel_statistics

if TYPE_CHECKING:
    from vibesensor.domain import TestRun


def summarize_origin(findings: tuple[DomainFinding, ...]) -> VibrationOrigin | None:
    """Return the most-likely origin as a domain value object."""
    return VibrationOrigin.from_ranked_findings(findings)


class RunAnalysis:
    """Typed analysis facade around a single prepared diagnostics run."""

    __slots__ = (
        "_run",
        "_file_name",
        "_language",
        "_include_samples",
        "_findings_builder",
        "_prepared",
        "_accel_stats",
        "_test_run",
    )

    def __init__(
        self,
        run: DiagnosticsRunInput,
        *,
        file_name: str = "run",
        lang: str | None = None,
        include_samples: bool = True,
        findings_builder: FindingsBuilder | None = None,
    ) -> None:
        self._run = run
        self._file_name = file_name
        self._language = normalize_lang(lang)
        self._include_samples = include_samples
        self._findings_builder = findings_builder
        self._test_run: TestRun | None = None

        _validate_required_strength_metrics(self._run.samples)
        self._prepared = prepare_run_data(self._run.context, self._run.samples)
        self._accel_stats = compute_accel_statistics(
            self._run.samples,
            self._run.context.sensor_model,
        )

    @property
    def prepared(self) -> PreparedRunData:
        return self._prepared

    @property
    def accel_stats(self) -> AccelStatistics:
        return self._accel_stats

    @property
    def language(self) -> str:
        return self._language

    @property
    def test_run(self) -> TestRun | None:
        return self._test_run

    def summarize(self) -> AnalysisResult:
        """Run the full typed diagnostics pipeline."""

        result = execute_analysis(
            context=self._run.context,
            samples=self._run.samples,
            file_name=self._file_name,
            language=self._language,
            include_samples=self._include_samples,
            prepared=self._prepared,
            accel_stats=self._accel_stats,
            findings_builder=self._findings_builder,
        )
        self._test_run = result.test_run
        return result


def build_findings_for_sensor_frames(
    *,
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    lang: str | None = None,
    findings_builder: FindingsBuilder | None = None,
) -> tuple[DomainFinding, ...]:
    """Build findings from the canonical typed diagnostics inputs."""
    run = build_diagnostics_run_input(metadata, samples, file_name="run")
    _validate_required_strength_metrics(run.samples)
    prepared = prepare_run_data(run.context, run.samples)
    return build_findings_for_typed_samples(
        context=run.context,
        samples=run.samples,
        language=normalize_lang(lang),
        prepared=prepared,
        findings_builder=findings_builder,
    )


__all__ = [
    "AnalysisResult",
    "RunAnalysis",
    "build_findings_for_sensor_frames",
    "summarize_origin",
]
