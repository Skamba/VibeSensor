"""History-side report preparation and prepared-input handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.report_interpretation import (
    PrimaryReportFacts,
)
from vibesensor.shared.boundaries.report_payload_gate import has_projectable_report_payload
from vibesensor.shared.boundaries.report_renderer_payload import (
    PreparedReportRendererPayload,
    build_report_renderer_payload,
)
from vibesensor.shared.boundaries.test_run_reconstruction import test_run_from_summary
from vibesensor.shared.run_context_warning import RunContextWarningsInput
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummary,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.helpers import safe_filename
from vibesensor.use_cases.history.report_cache import ReportPdfCacheKey
from vibesensor.use_cases.history.report_facts import (
    PreparedReportFacts,
    prepare_report_facts,
)

if TYPE_CHECKING:
    from vibesensor.domain import TestRun

__all__ = [
    "PreparedReportFacts",
    "PreparedReportInput",
    "PreparedReportRendererPayload",
    "PrimaryReportFacts",
    "ValidatedPreparedReportInput",
    "prepare_persisted_report_input",
    "prepare_report_input",
    "validate_prepared_report_input",
]


def _default_report_filename(payload: Mapping[str, object]) -> str:
    """Derive the default PDF filename from stable report-identifying payload fields."""
    run_id = str(payload.get("run_id") or payload.get("file_name") or "report")
    return f"{safe_filename(run_id)}_report.pdf"


@dataclass(frozen=True, slots=True)
class PreparedReportInput:
    """Resolved report input ready for PDF mapping and rendering.

    Invariants:
    - ``domain_test_run`` is reconstructed at most once and shared across the
      downstream PDF mapping helpers as the authoritative report aggregate.
    - ``report_facts`` contains the semantic report facts that the PDF adapter
      needs so it does not have to call back into history-layer interpretation.
    - ``renderer_payload`` contains only the minimal final-edge payload that the
      PDF mapper still needs after domain/report preparation is complete.
    - ``ReportMappingContext`` is adapter-owned and derived later inside
      ``vibesensor.adapters.pdf.report_context`` from this validated handoff.
    - ``language`` is canonicalized once so the renderer consumes one
      consistent locale choice.
    - ``domain_test_run`` and ``report_facts`` may still be ``None`` for
      non-projectable inputs.
    """

    renderer_payload: PreparedReportRendererPayload
    language: str
    filename: str
    domain_test_run: TestRun | None
    cache_key: ReportPdfCacheKey | None = None
    report_facts: PreparedReportFacts | None = None


@dataclass(frozen=True, slots=True)
class ValidatedPreparedReportInput:
    """Prepared report handoff validated for PDF mapping.

    This mapping-ready shape guarantees the domain aggregate and prepared report
    facts are both present before adapter-side context assembly and mapping begin.
    """

    renderer_payload: PreparedReportRendererPayload
    language: str
    filename: str
    domain_test_run: TestRun
    report_facts: PreparedReportFacts
    cache_key: ReportPdfCacheKey | None = None


def validate_prepared_report_input(
    prepared: PreparedReportInput | ValidatedPreparedReportInput,
) -> ValidatedPreparedReportInput:
    """Validate that the prepared report seam is ready for PDF mapping.

    Checks both field presence and cross-object consistency so mismatched
    prepared data fails at the history/report seam instead of surfacing
    later inside template mapping.
    """
    if isinstance(prepared, ValidatedPreparedReportInput):
        return prepared
    if prepared.domain_test_run is None:
        raise ValueError("PreparedReportInput must include a domain_test_run for report mapping")
    if prepared.report_facts is None:
        raise ValueError("PreparedReportInput must include report_facts for report mapping")

    return ValidatedPreparedReportInput(
        renderer_payload=prepared.renderer_payload,
        language=prepared.language,
        filename=prepared.filename,
        domain_test_run=prepared.domain_test_run,
        report_facts=prepared.report_facts,
        cache_key=prepared.cache_key,
    )


def _reconstruct_report_test_run(payload: Mapping[str, object]) -> TestRun | None:
    """Rebuild the report domain aggregate only when the payload is projectable."""
    if not has_projectable_report_payload(payload):
        return None
    return test_run_from_summary(payload)


def _build_prepared_report_input(
    payload: Mapping[str, object],
    *,
    filename: str | None,
    language: str | None,
    cache_key: ReportPdfCacheKey | None,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportInput:
    """Assemble the canonical history-side report handoff for PDF rendering."""
    domain_test_run = _reconstruct_report_test_run(payload)
    prepared_language = str(normalize_lang(language or payload.get("lang")))
    renderer_payload = build_report_renderer_payload(payload)
    report_facts = (
        prepare_report_facts(payload, test_run=domain_test_run, warnings=warnings)
        if domain_test_run is not None
        else None
    )
    return PreparedReportInput(
        renderer_payload=renderer_payload,
        language=prepared_language,
        filename=filename or _default_report_filename(payload),
        domain_test_run=domain_test_run,
        cache_key=cache_key,
        report_facts=report_facts,
    )


def prepare_report_input(
    analysis_summary: AnalysisSummary,
    *,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a direct summary payload for domain-first report mapping."""
    return _build_prepared_report_input(
        analysis_summary,
        filename=filename,
        language=language,
        cache_key=cache_key,
    )


def prepare_persisted_report_input(
    analysis: PersistedAnalysis,
    *,
    warnings: RunContextWarningsInput = None,
    filename: str | None = None,
    language: str | None = None,
    cache_key: ReportPdfCacheKey | None = None,
) -> PreparedReportInput:
    """Prepare a persisted history payload for domain-first report mapping."""
    return _build_prepared_report_input(
        analysis,
        filename=filename,
        language=language,
        cache_key=cache_key,
        warnings=warnings,
    )
