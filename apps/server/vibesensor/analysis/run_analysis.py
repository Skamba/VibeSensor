"""Typed diagnostics analysis entrypoints."""

from __future__ import annotations

from vibesensor.analysis._analysis_result import AnalysisResult
from vibesensor.analysis._analysis_result_builder import build_analysis_result
from vibesensor.analysis._run_input import (
    DiagnosticsRunInput,
)
from vibesensor.analysis._validation import _validate_required_strength_metrics
from vibesensor.analysis.findings_bundle import build_findings_bundle
from vibesensor.analysis.prepared_analysis_context import (
    prepare_analysis_context,
)
from vibesensor.analysis.run_data_preparation import prepare_run_data
from vibesensor.analysis.statistics import compute_accel_statistics
from vibesensor.report.i18n import normalize_lang


class RunAnalysis:
    """Typed analysis facade around a single prepared diagnostics run."""

    __slots__ = (
        "_run",
        "_file_name",
        "_language",
        "_prepared",
        "_accel_stats",
    )

    def __init__(
        self,
        run: DiagnosticsRunInput,
        *,
        file_name: str = "run",
        lang: str | None = None,
    ) -> None:
        self._run = run
        self._file_name = file_name
        self._language = normalize_lang(lang)

        _validate_required_strength_metrics(self._run.samples)
        self._prepared = prepare_run_data(self._run.context, self._run.samples)
        self._accel_stats = compute_accel_statistics(
            self._run.samples,
            self._run.context.sensor_model,
        )

    def summarize(self) -> AnalysisResult:
        """Run the full typed diagnostics pipeline."""

        analysis_context = prepare_analysis_context(
            context=self._run.context,
            samples=self._run.samples,
            file_name=self._file_name,
            language=self._language,
            prepared=self._prepared,
            accel_stats=self._accel_stats,
            window_means=self._run.window_means,
        )
        result = build_analysis_result(analysis_context, build_findings_bundle(analysis_context))
        return result


__all__ = [
    "AnalysisResult",
    "RunAnalysis",
]
