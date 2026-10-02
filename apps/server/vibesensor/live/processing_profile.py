"""Processing-profile identifiers shared across live and diagnostic paths."""

from __future__ import annotations

from typing import Literal

from vibesensor.shared.types.json_types import JsonObject

type ProcessingProfile = Literal["live_display", "diagnostic_raw", "diagnostic_filtered"]
type ProcessingFilterId = Literal["median_3_sample_time_domain"]

PROCESSING_PROFILE_VERSION = "processing-profiles-v1"
PROCESSING_PROFILE_LIVE_DISPLAY: ProcessingProfile = "live_display"
PROCESSING_PROFILE_DIAGNOSTIC_RAW: ProcessingProfile = "diagnostic_raw"
PROCESSING_PROFILE_DIAGNOSTIC_FILTERED: ProcessingProfile = "diagnostic_filtered"
PROCESSING_FILTER_MEDIAN_3_SAMPLE: ProcessingFilterId = "median_3_sample_time_domain"
MEDIAN_FILTER_WINDOW_SAMPLES = 3

__all__ = [
    "MEDIAN_FILTER_WINDOW_SAMPLES",
    "PROCESSING_FILTER_MEDIAN_3_SAMPLE",
    "PROCESSING_PROFILE_DIAGNOSTIC_FILTERED",
    "PROCESSING_PROFILE_DIAGNOSTIC_RAW",
    "PROCESSING_PROFILE_LIVE_DISPLAY",
    "PROCESSING_PROFILE_VERSION",
    "ProcessingFilterId",
    "ProcessingProfile",
    "processing_profile_row",
]


def processing_profile_row(
    *,
    profile: ProcessingProfile,
    applies_to: str,
    filter_chain: tuple[ProcessingFilterId, ...],
    enabled: bool,
    raw_evidence_preserved: bool,
) -> JsonObject:
    return {
        "processing_profile": profile,
        "applies_to": applies_to,
        "filter_chain": list(filter_chain),
        "enabled": enabled,
        "raw_evidence_preserved": raw_evidence_preserved,
    }
