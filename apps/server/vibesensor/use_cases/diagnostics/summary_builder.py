"""Structured orchestration for building analysis summaries from run samples."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from vibesensor.domain import (
    Finding as DomainFinding,
)
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._context import DiagnosticsContext
from vibesensor.use_cases.diagnostics._types import (
    AccelStatistics,
    AnalysisSampleInput,
    normalize_analysis_samples,
)
from vibesensor.use_cases.diagnostics.findings import _build_findings
from vibesensor.use_cases.diagnostics.helpers import (
    _validate_required_strength_metrics,
)
from vibesensor.use_cases.diagnostics.run_data_preparation import (
    PreparedRunData,
    prepare_run_data,
)
from vibesensor.use_cases.diagnostics.statistics import compute_accel_statistics

from . import _summary_result, _summary_steps

if TYPE_CHECKING:
    from vibesensor.domain import TestRun

# ═══════════════════════════════════════════════════════════════════════════
# Origin helpers
# ═══════════════════════════════════════════════════════════════════════════


def summarize_origin(findings: tuple[DomainFinding, ...]) -> VibrationOrigin | None:
    """Return the most-likely origin as a domain value object."""
    return VibrationOrigin.from_ranked_findings(findings)


AnalysisResult = _summary_result.AnalysisResult


class RunAnalysis:
    """Cohesive object around a single analyzed run.

    Owns run timing, speed/phase preparation, data quality, suitability,
    sensor bundle, findings bundle, and app-level result assembly. It keeps
    all derived state together so boundary serializers can explicitly
    project the final wire payload at the edges.
    """

    __slots__ = (
        "_context",
        "_raw_samples",
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
        metadata: JsonObject,
        samples: Sequence[AnalysisSampleInput],
        *,
        file_name: str = "run",
        lang: str | None = None,
        include_samples: bool = True,
        findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
    ) -> None:
        self._context = DiagnosticsContext.from_metadata(metadata, file_name=file_name)
        self._raw_samples, self._samples = normalize_analysis_samples(samples)
        self._file_name = file_name
        self._language = normalize_lang(lang)
        self._include_samples = include_samples
        self._findings_builder = findings_builder
        self._test_run: TestRun | None = None

        _validate_required_strength_metrics(self._samples)
        self._prepared = prepare_run_data(self._context, self._samples)
        self._accel_stats: AccelStatistics = compute_accel_statistics(
            self._samples,
            self._context.sensor_model,
        )

    # -- read-only access --------------------------------------------------

    @property
    def prepared(self) -> PreparedRunData:
        return self._prepared

    @property
    def accel_stats(self) -> AccelStatistics:
        return self._accel_stats

    @property
    def language(self) -> str:
        lang: str = self._language
        return lang

    @property
    def test_run(self) -> TestRun | None:
        return self._test_run

    # -- orchestration -----------------------------------------------------

    def summarize(self) -> AnalysisResult:
        """Run the full analysis pipeline and return the app-level result.

        Returns an :class:`AnalysisResult` carrying the domain/app artifacts
        needed for explicit boundary serialization elsewhere.
        """
        reference_complete, run_suitability, overall_strength_band_key = (
            _summary_steps.build_run_suitability_bundle(
                self._context,
                self._samples,
                prepared=self._prepared,
                accel_stats=self._accel_stats,
            )
        )
        sensor_locations, connected_locations, sensor_intensity_by_location = (
            _summary_steps.build_sensor_bundle(
                self._samples,
                language=self._language,
                per_sample_phases=self._prepared.per_sample_phases,
            )
        )
        (
            most_likely_origin,
            phase_timeline,
            domain_findings,
            domain_top_causes,
        ) = _summary_steps.build_findings_bundle(
            self._context,
            self._samples,
            language=self._language,
            prepared=self._prepared,
            overall_strength_band_key=overall_strength_band_key,
            has_reference_gaps=not reference_complete,
            sensor_count=len(sensor_locations),
            findings_builder=self._findings_builder,
        )
        result = _summary_result.build_analysis_result(
            file_name=self._file_name,
            context=self._context,
            samples=self._samples,
            raw_samples=self._raw_samples,
            language=self._language,
            include_samples=self._include_samples,
            prepared=self._prepared,
            accel_stats=self._accel_stats,
            sensor_locations=sensor_locations,
            connected_locations=connected_locations,
            sensor_intensity_by_location=sensor_intensity_by_location,
            reference_complete=reference_complete,
            run_suitability=run_suitability,
            most_likely_origin=most_likely_origin,
            phase_timeline=phase_timeline,
            domain_findings=domain_findings,
            domain_top_causes=domain_top_causes,
        )
        self._test_run = result.test_run
        return result


def build_findings_for_samples(
    *,
    metadata: JsonObject,
    samples: Sequence[AnalysisSampleInput],
    lang: str | None = None,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> tuple[DomainFinding, ...]:
    """Build the findings list from *samples* using the full analysis pipeline."""
    language = normalize_lang(lang)
    rows = normalize_analysis_samples(samples)[1]
    _validate_required_strength_metrics(rows)
    context = DiagnosticsContext.from_metadata(metadata, file_name="run")
    prepared = prepare_run_data(context, rows)
    builder = findings_builder or _build_findings
    return builder(
        context=context,
        samples=rows,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
    )
