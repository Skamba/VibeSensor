"""Typed report-facing view of persisted analysis metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.shared.boundaries.codecs.scalars import coerce_count, text_or_none

__all__ = [
    "REPORT_ANALYSIS_METADATA_STABLE_KEYS",
    "ReportAnalysisMetadata",
    "ReportWholeRunContextMetadata",
    "report_analysis_metadata_from_mapping",
    "report_analysis_metadata_from_payload",
]

REPORT_ANALYSIS_METADATA_STABLE_KEYS = frozenset(
    {
        "raw_backed_sample_count",
        "raw_capture_available",
        "raw_capture_finalize_status",
        "raw_capture_loss_policy_gate_whole_run",
        "raw_capture_loss_policy_severity",
        "raw_capture_mode",
        "whole_run_artifacts_available",
        "whole_run_context_assumed_speed_window_count",
        "whole_run_context_available",
        "whole_run_context_full_window_count",
        "whole_run_context_interval_count",
        "whole_run_context_low_speed_window_count",
        "whole_run_context_missing_rpm_window_count",
        "whole_run_context_missing_speed_window_count",
        "whole_run_context_missing_window_count",
        "whole_run_context_partial_window_count",
        "whole_run_context_stale_rpm_window_count",
        "whole_run_context_stale_speed_window_count",
        "whole_run_context_unstable_speed_window_count",
        "whole_run_context_window_count",
        "whole_run_diagnosis_summaries_available",
        "whole_run_diagnosis_summary_count",
        "whole_run_order_family_summaries_available",
        "whole_run_order_family_summary_count",
        "whole_run_spatial_coherence_available",
        "whole_run_spatial_coherence_summary_count",
    }
)


@dataclass(frozen=True, slots=True)
class ReportWholeRunContextMetadata:
    """Typed counts for stable whole-run context metadata keys."""

    window_count: int | None
    interval_count: int | None
    full_window_count: int | None
    partial_window_count: int | None
    missing_window_count: int | None
    missing_speed_window_count: int | None
    missing_rpm_window_count: int | None
    stale_speed_window_count: int | None
    stale_rpm_window_count: int | None
    low_speed_window_count: int | None
    unstable_speed_window_count: int | None
    assumed_speed_window_count: int | None


@dataclass(frozen=True, slots=True)
class ReportAnalysisMetadata:
    """Typed report boundary object for stable persisted analysis metadata keys."""

    present: bool
    raw_backed_sample_count: int
    raw_capture_available: bool | None
    raw_capture_finalize_status: str | None
    raw_capture_loss_policy_severity: str | None
    raw_capture_loss_policy_gate_whole_run: bool
    raw_capture_mode: str | None
    whole_run_artifacts_available: bool
    whole_run_context_available: bool
    whole_run_order_family_summaries_available: bool
    whole_run_spatial_coherence_available: bool
    whole_run_diagnosis_summaries_available: bool
    whole_run_diagnosis_summary_count: int
    whole_run_order_family_summary_count: int
    whole_run_spatial_coherence_summary_count: int
    whole_run_context: ReportWholeRunContextMetadata

    @property
    def data_basis(self) -> str:
        if self.raw_capture_mode in {"raw_backed", "partial_raw_backed", "summary_only"}:
            return self.raw_capture_mode
        return "raw_backed" if self.raw_backed_sample_count > 0 else "summary_only"

    @property
    def has_fatal_raw_capture_loss(self) -> bool:
        return (
            self.raw_capture_loss_policy_severity == "fatal"
            or self.raw_capture_loss_policy_gate_whole_run
        )

    @property
    def is_summary_only_capture(self) -> bool:
        return self.raw_capture_mode == "summary_only" or (
            self.raw_capture_mode is None and self.raw_backed_sample_count <= 0
        )

    @property
    def is_summary_only_context_fallback(self) -> bool:
        if self.raw_capture_mode == "summary_only":
            return True
        if self.raw_capture_mode == "raw_backed":
            return False
        return self.raw_backed_sample_count <= 0

    def has_partial_whole_run_inputs(
        self,
        *,
        has_whole_run_context_intervals: bool,
        has_whole_run_order_summaries: bool,
        has_whole_run_spatial_summaries: bool,
    ) -> bool:
        return bool(
            has_whole_run_context_intervals
            or has_whole_run_order_summaries
            or has_whole_run_spatial_summaries
            or self.whole_run_artifacts_available
            or self.whole_run_context_available
            or self.whole_run_order_family_summaries_available
            or self.whole_run_spatial_coherence_available
        )


def report_analysis_metadata_from_payload(
    payload: Mapping[str, object],
) -> ReportAnalysisMetadata:
    raw_metadata = payload.get("analysis_metadata")
    raw = raw_metadata if isinstance(raw_metadata, Mapping) else None
    return report_analysis_metadata_from_mapping(raw)


def report_analysis_metadata_from_mapping(
    raw: Mapping[str, object] | None,
) -> ReportAnalysisMetadata:
    return ReportAnalysisMetadata(
        present=raw is not None,
        raw_backed_sample_count=_count(raw, "raw_backed_sample_count"),
        raw_capture_available=_optional_bool(raw, "raw_capture_available"),
        raw_capture_finalize_status=_text(raw, "raw_capture_finalize_status"),
        raw_capture_loss_policy_severity=_text(raw, "raw_capture_loss_policy_severity"),
        raw_capture_loss_policy_gate_whole_run=_flag(
            raw,
            "raw_capture_loss_policy_gate_whole_run",
        ),
        raw_capture_mode=_text(raw, "raw_capture_mode"),
        whole_run_artifacts_available=_flag(raw, "whole_run_artifacts_available"),
        whole_run_context_available=_flag(raw, "whole_run_context_available"),
        whole_run_order_family_summaries_available=_flag(
            raw,
            "whole_run_order_family_summaries_available",
        ),
        whole_run_spatial_coherence_available=_flag(
            raw,
            "whole_run_spatial_coherence_available",
        ),
        whole_run_diagnosis_summaries_available=_flag(
            raw,
            "whole_run_diagnosis_summaries_available",
        ),
        whole_run_diagnosis_summary_count=_count(raw, "whole_run_diagnosis_summary_count"),
        whole_run_order_family_summary_count=_count(
            raw,
            "whole_run_order_family_summary_count",
        ),
        whole_run_spatial_coherence_summary_count=_count(
            raw,
            "whole_run_spatial_coherence_summary_count",
        ),
        whole_run_context=ReportWholeRunContextMetadata(
            window_count=_optional_count(raw, "whole_run_context_window_count"),
            interval_count=_optional_count(raw, "whole_run_context_interval_count"),
            full_window_count=_optional_count(raw, "whole_run_context_full_window_count"),
            partial_window_count=_optional_count(
                raw,
                "whole_run_context_partial_window_count",
            ),
            missing_window_count=_optional_count(raw, "whole_run_context_missing_window_count"),
            missing_speed_window_count=_optional_count(
                raw,
                "whole_run_context_missing_speed_window_count",
            ),
            missing_rpm_window_count=_optional_count(
                raw,
                "whole_run_context_missing_rpm_window_count",
            ),
            stale_speed_window_count=_optional_count(
                raw,
                "whole_run_context_stale_speed_window_count",
            ),
            stale_rpm_window_count=_optional_count(
                raw,
                "whole_run_context_stale_rpm_window_count",
            ),
            low_speed_window_count=_optional_count(
                raw,
                "whole_run_context_low_speed_window_count",
            ),
            unstable_speed_window_count=_optional_count(
                raw,
                "whole_run_context_unstable_speed_window_count",
            ),
            assumed_speed_window_count=_optional_count(
                raw,
                "whole_run_context_assumed_speed_window_count",
            ),
        ),
    )


def _text(raw: Mapping[str, object] | None, key: str) -> str | None:
    return text_or_none(raw.get(key)) if raw is not None else None


def _count(raw: Mapping[str, object] | None, key: str) -> int:
    return coerce_count(raw.get(key)) if raw is not None else 0


def _optional_count(raw: Mapping[str, object] | None, key: str) -> int | None:
    if raw is None or key not in raw:
        return None
    return coerce_count(raw.get(key))


def _flag(raw: Mapping[str, object] | None, key: str) -> bool:
    return bool(raw is not None and raw.get(key))


def _optional_bool(raw: Mapping[str, object] | None, key: str) -> bool | None:
    if raw is None:
        return None
    value = raw.get(key)
    return value if isinstance(value, bool) else None
