"""Typed diagnostics analysis entrypoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from vibesensor.analysis._analysis_result import AnalysisResult
from vibesensor.analysis._analysis_result_builder import build_analysis_result
from vibesensor.analysis._run_input import (
    DiagnosticsRunInput,
    build_diagnostics_run_input,
)
from vibesensor.analysis._types import AccelStatistics
from vibesensor.analysis._validation import _validate_required_strength_metrics
from vibesensor.analysis.findings import _build_findings
from vibesensor.analysis.findings_bundle import build_findings_bundle
from vibesensor.analysis.prepared_analysis_context import (
    build_findings_request,
    prepare_analysis_context,
)
from vibesensor.analysis.run_data_preparation import PreparedRunData, prepare_run_data
from vibesensor.analysis.statistics import compute_accel_statistics
from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.report.i18n import normalize_lang

if TYPE_CHECKING:
    from vibesensor.domain.test_run import TestRun


class RunAnalysis:
    """Typed analysis facade around a single prepared diagnostics run."""

    __slots__ = (
        "_run",
        "_file_name",
        "_language",
        "_include_samples",
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
    ) -> None:
        self._run = run
        self._file_name = file_name
        self._language = normalize_lang(lang)
        self._include_samples = include_samples
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

        analysis_context = prepare_analysis_context(
            context=self._run.context,
            samples=self._run.samples,
            file_name=self._file_name,
            language=self._language,
            include_samples=self._include_samples,
            prepared=self._prepared,
            accel_stats=self._accel_stats,
        )
        result = build_analysis_result(analysis_context, build_findings_bundle(analysis_context))
        self._test_run = result.test_run
        return result


def build_findings_for_sensor_frames(
    *,
    metadata: RunMetadata,
    samples: Sequence[SensorFrame],
    lang: str | None = None,
) -> tuple[DomainFinding, ...]:
    """Build findings from the canonical typed diagnostics inputs."""
    run = build_diagnostics_run_input(metadata, samples, file_name="run")
    _validate_required_strength_metrics(run.samples)
    prepared = prepare_run_data(run.context, run.samples)
    return _build_findings(
        build_findings_request(
            context=run.context,
            samples=run.samples,
            language=normalize_lang(lang),
            prepared=prepared,
        )
    )


__all__ = [
    "AnalysisResult",
    "RunAnalysis",
    "build_findings_for_sensor_frames",
]
