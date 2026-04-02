"""Pure execution steps for typed diagnostics analysis runs."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import Finding as DomainFinding
from vibesensor.shared.types.run_schema import RunMetadata

from ._analysis_models import FindingsBuilder
from ._analysis_result import AnalysisResult
from ._analysis_result_builder import build_analysis_result
from ._types import AccelStatistics, Sample
from .findings import _build_findings
from .findings_bundle import build_findings_bundle
from .prepared_analysis_context import build_findings_request, prepare_analysis_context
from .run_data_preparation import PreparedRunData


def execute_analysis(
    *,
    context: RunMetadata,
    samples: Sequence[Sample],
    file_name: str,
    language: str,
    include_samples: bool,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
    findings_builder: FindingsBuilder | None,
) -> AnalysisResult:
    """Execute the diagnostics pipeline for an already-typed run."""

    analysis_context = prepare_analysis_context(
        context=context,
        samples=samples,
        file_name=file_name,
        language=language,
        include_samples=include_samples,
        prepared=prepared,
        accel_stats=accel_stats,
    )
    findings_bundle = build_findings_bundle(
        analysis_context,
        findings_builder=findings_builder,
    )
    return build_analysis_result(analysis_context, findings_bundle)


def build_findings_for_typed_samples(
    *,
    context: RunMetadata,
    samples: Sequence[Sample],
    language: str,
    prepared: PreparedRunData,
    findings_builder: FindingsBuilder | None = None,
) -> tuple[DomainFinding, ...]:
    """Build findings from canonical typed diagnostics inputs."""

    builder = findings_builder or _build_findings
    return builder(
        build_findings_request(
            context=context,
            samples=samples,
            language=language,
            prepared=prepared,
        )
    )
