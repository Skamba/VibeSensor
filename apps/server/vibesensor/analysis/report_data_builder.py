"""Compatibility facade for summary-to-report mapping."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..report.report_data import (
    DataTrustItem,
    NextStep,
    PeakRow,
    ReportTemplateData,
    SystemFindingCard,
)
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from .report_mapping_common import (
    extract_confidence as _extract_confidence_impl,
)
from .report_mapping_common import (
    finding_strength_db as _finding_strength_values_impl,
)
from .report_mapping_common import (
    human_source as _human_source_impl,
)
from .report_mapping_common import (
    is_i18n_ref as _is_i18n_ref_impl,
)
from .report_mapping_common import (
    order_label_human as _order_label_human_impl,
)
from .report_mapping_common import (
    peak_classification_text as _peak_classification_text_impl,
)
from .report_mapping_common import (
    resolve_i18n as _resolve_i18n_impl,
)
from .report_mapping_components import (
    build_data_trust_from_summary as _build_data_trust_from_summary_impl,
)
from .report_mapping_components import (
    build_next_steps_from_summary as _build_next_steps_from_summary_impl,
)
from .report_mapping_components import (
    build_peak_rows_from_plots as _build_peak_rows_from_plots_impl,
)
from .report_mapping_components import (
    build_system_cards as _build_system_cards_impl,
)
from .report_mapping_components import (
    compute_location_hotspot_rows as _compute_location_hotspot_rows_impl,
)
from .report_mapping_components import (
    has_relevant_reference_gap as _has_relevant_reference_gap_impl,
)
from .report_mapping_components import (
    top_strength_values as _top_strength_values_impl,
)
from .report_mapping_pipeline import build_report_template_data


def _is_i18n_ref(value: object) -> bool:
    return _is_i18n_ref_impl(value)


def _resolve_i18n(lang: str, value: object) -> str:
    from ..report_i18n import tr as _tr

    return _resolve_i18n_impl(lang, value, tr=lambda key, **kw: _tr(lang, key, **kw))


def _order_label_human(lang: str, label: str) -> str:
    return _order_label_human_impl(lang, label)


def _human_source(source: object, *, tr: Callable[[str], str]) -> str:
    return _human_source_impl(source, tr=tr)


def _finding_strength_values(finding: dict[str, Any]) -> float | None:
    return _finding_strength_values_impl(finding)


def _top_strength_values(
    summary: dict,
    *,
    effective_causes: list[dict] | None = None,
) -> float | None:
    return _top_strength_values_impl(summary, effective_causes=effective_causes)


def _peak_classification_text(value: object, tr: Callable[..., str]) -> str:
    return _peak_classification_text_impl(value, tr)


def _extract_confidence(d: dict) -> float:
    return _extract_confidence_impl(d)


def _has_relevant_reference_gap(findings: list[dict], primary_source: object) -> bool:
    return _has_relevant_reference_gap_impl(findings, primary_source)


def _compute_location_hotspot_rows(sensor_intensity: list[dict]) -> list[dict]:
    return _compute_location_hotspot_rows_impl(sensor_intensity)


def _build_next_steps_from_summary(
    summary: dict,
    *,
    tier: str,
    cert_reason: str,
    lang: str,
    tr: Callable,
) -> list[NextStep]:
    return _build_next_steps_from_summary_impl(
        summary,
        tier=tier,
        cert_reason=cert_reason,
        lang=lang,
        tr=tr,
    )


def _build_data_trust_from_summary(
    summary: dict,
    *,
    lang: str,
    tr: Callable,
) -> list[DataTrustItem]:
    return _build_data_trust_from_summary_impl(summary, lang=lang, tr=tr)


def _build_peak_rows_from_plots(
    summary: dict,
    *,
    lang: str,
    tr: Callable,
) -> list[PeakRow]:
    return _build_peak_rows_from_plots_impl(summary, lang=lang, tr=tr)


def _build_system_cards(
    top_causes: list[dict],
    findings_non_ref: list[dict],
    findings: list[dict],
    tier: str,
    lang: str,
    tr: Callable,
) -> list[SystemFindingCard]:
    return _build_system_cards_impl(top_causes, findings_non_ref, findings, tier, lang, tr)


def map_summary(summary: dict) -> ReportTemplateData:
    """Map a run summary dict to the report template data model."""
    lang = str(normalize_lang(summary.get("lang")))

    def tr(key: str, **kw: object) -> str:
        return str(_tr(lang, key, **kw))

    return build_report_template_data(summary, lang=lang, tr=tr)
