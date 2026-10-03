"""Typed report-facing view of persisted analysis metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.common.scalars import coerce_count, text_or_none

__all__ = [
    "REPORT_ANALYSIS_METADATA_STABLE_KEYS",
    "ReportAnalysisMetadata",
    "report_analysis_metadata_from_mapping",
    "report_analysis_metadata_from_payload",
]

REPORT_ANALYSIS_METADATA_STABLE_KEYS = frozenset(
    {
        "raw_backed_sample_count",
        "raw_capture_available",
        "raw_capture_finalize_status",
        "raw_capture_loss_policy_severity",
        "raw_capture_mode",
    }
)


@dataclass(frozen=True, slots=True)
class ReportAnalysisMetadata:
    """Typed report boundary object for stable persisted analysis metadata keys."""

    present: bool
    raw_backed_sample_count: int
    raw_capture_available: bool | None
    raw_capture_finalize_status: str | None
    raw_capture_loss_policy_severity: str | None
    raw_capture_mode: str | None

    @property
    def data_basis(self) -> str:
        if self.raw_capture_mode in {"raw_backed", "partial_raw_backed", "summary_only"}:
            return self.raw_capture_mode
        return "raw_backed" if self.raw_backed_sample_count > 0 else "summary_only"

    @property
    def has_fatal_raw_capture_loss(self) -> bool:
        return self.raw_capture_loss_policy_severity == "fatal"

    @property
    def is_summary_only_capture(self) -> bool:
        return self.raw_capture_mode == "summary_only" or (
            self.raw_capture_mode is None and self.raw_backed_sample_count <= 0
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
        raw_capture_mode=_text(raw, "raw_capture_mode"),
    )


def _text(raw: Mapping[str, object] | None, key: str) -> str | None:
    return text_or_none(raw.get(key)) if raw is not None else None


def _count(raw: Mapping[str, object] | None, key: str) -> int:
    return coerce_count(raw.get(key)) if raw is not None else 0


def _optional_bool(raw: Mapping[str, object] | None, key: str) -> bool | None:
    if raw is None:
        return None
    value = raw.get(key)
    return value if isinstance(value, bool) else None
