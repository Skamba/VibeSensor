"""Public summary/selection facade for the diagnosis pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .findings.builder import _build_findings
from .ranking import phase_adjusted_ranking_score as _phase_ranking_score_impl
from .summary_builder import (
    annotate_peaks_with_order_labels as _annotate_peaks_with_order_labels,
)
from .summary_builder import (
    build_findings_for_samples,
    summarize_log,
)
from .summary_builder import (
    normalize_lang as _normalize_lang_impl,
)
from .summary_builder import summarize_run_data as _summarize_run_data_impl
from .summary_pipeline import build_phase_timeline as _build_phase_timeline_impl
from .summary_pipeline import (
    build_run_suitability_checks as _build_run_suitability_checks_impl,
)
from .summary_pipeline import compute_accel_statistics as _compute_accel_statistics_impl
from .summary_pipeline import compute_run_timing as _compute_run_timing_impl
from .summary_pipeline import summarize_origin as _most_likely_origin_summary_impl
from .top_cause_selection import confidence_label, select_top_causes

__all__ = [
    "_annotate_peaks_with_order_labels",
    "_build_findings",
    "_build_phase_timeline",
    "_build_run_suitability_checks",
    "_compute_accel_statistics",
    "_compute_run_timing",
    "_most_likely_origin_summary",
    "_normalize_lang",
    "_phase_ranking_score",
    "build_findings_for_samples",
    "confidence_label",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]


def _normalize_lang(lang: object) -> str:
    return _normalize_lang_impl(lang)


def _phase_ranking_score(finding: dict[str, Any]) -> float:
    return _phase_ranking_score_impl(finding)


def _most_likely_origin_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return _most_likely_origin_summary_impl(findings)


def _compute_run_timing(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    file_name: str,
) -> tuple[str, datetime | None, datetime | None, float]:
    return _compute_run_timing_impl(metadata, samples, file_name)


def _compute_accel_statistics(
    samples: list[dict[str, Any]],
    sensor_model: object,
) -> dict[str, Any]:
    return _compute_accel_statistics_impl(samples, sensor_model)


def _build_run_suitability_checks(
    steady_speed: bool,
    speed_sufficient: bool,
    sensor_ids: set[str],
    reference_complete: bool,
    sat_count: int,
    samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _build_run_suitability_checks_impl(
        steady_speed=steady_speed,
        speed_sufficient=speed_sufficient,
        sensor_ids=sensor_ids,
        reference_complete=reference_complete,
        sat_count=sat_count,
        samples=samples,
    )


def _build_phase_timeline(
    phase_segments: list[Any],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _build_phase_timeline_impl(phase_segments, findings, min_confidence=0.25)


def summarize_run_data(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> dict[str, Any]:
    return _summarize_run_data_impl(
        metadata,
        samples,
        lang=lang,
        file_name=file_name,
        include_samples=include_samples,
        findings_builder=_build_findings,
    )
