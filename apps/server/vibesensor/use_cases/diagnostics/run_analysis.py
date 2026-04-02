"""Typed diagnostics analysis entrypoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.sensor_frame_codec import sensor_frames_from_rows
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.sensor_frame import SensorFrame

from ._analysis_models import FindingsBuilder
from ._context import DiagnosticsContext
from ._context_decode import build_diagnostics_context
from ._types import AccelStatistics
from ._validation import _validate_required_strength_metrics
from .analysis_pipeline import (
    AnalysisResult,
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
        "_context",
        "_samples",
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
        context: DiagnosticsContext,
        samples: Sequence[SensorFrame],
        *,
        file_name: str = "run",
        lang: str | None = None,
        include_samples: bool = True,
        findings_builder: FindingsBuilder | None = None,
    ) -> None:
        self._context = context
        self._samples = list(samples)
        self._file_name = file_name
        self._language = normalize_lang(lang)
        self._include_samples = include_samples
        self._findings_builder = findings_builder
        self._test_run: TestRun | None = None

        _validate_required_strength_metrics(self._samples)
        self._prepared = prepare_run_data(self._context, self._samples)
        self._accel_stats = compute_accel_statistics(
            self._samples,
            self._context.sensor_model,
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
            context=self._context,
            samples=self._samples,
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
    metadata: Mapping[str, object],
    samples: Sequence[SensorFrame],
    lang: str | None = None,
    findings_builder: FindingsBuilder | None = None,
) -> tuple[DomainFinding, ...]:
    """Build findings from the canonical typed diagnostics samples."""
    _validate_required_strength_metrics(samples)
    context = build_diagnostics_context(metadata, file_name="run")
    prepared = prepare_run_data(context, samples)
    return build_findings_for_typed_samples(
        context=context,
        samples=samples,
        language=normalize_lang(lang),
        prepared=prepared,
        findings_builder=findings_builder,
    )


def build_findings_for_samples(
    *,
    metadata: JsonObject,
    samples: Sequence[Mapping[str, object]],
    lang: str | None = None,
    findings_builder: FindingsBuilder | None = None,
) -> tuple[DomainFinding, ...]:
    """Decode boundary sample rows once, then build findings from typed frames."""
    return build_findings_for_sensor_frames(
        metadata=metadata,
        samples=sensor_frames_from_rows(samples),
        lang=lang,
        findings_builder=findings_builder,
    )


__all__ = [
    "AnalysisResult",
    "RunAnalysis",
    "build_findings_for_samples",
    "build_findings_for_sensor_frames",
    "summarize_origin",
]
