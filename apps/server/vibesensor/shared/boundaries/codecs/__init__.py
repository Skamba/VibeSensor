"""Canonical boundary codec package for typed domain snapshots and payloads."""

from .analysis_settings import (
    ANALYSIS_SETTINGS_FIELDS,
    ScalarSettings,
    ScalarSettingValue,
    analysis_settings_snapshot_from_mapping,
    analysis_settings_snapshot_items,
    analysis_settings_snapshot_to_metadata,
    sanitize_analysis_settings,
)
from .finding_evidence import finding_evidence_from_mapping
from .strength_metrics import (
    strength_metrics_from_mapping,
    strength_peak_from_mapping,
    strength_peak_payloads,
    strength_peak_to_payload,
    strength_peaks_from_sequence,
)
from .summaries import (
    driving_phase_summary_from_mapping,
    driving_phase_summary_to_payload,
    speed_profile_summary_from_mapping,
    speed_profile_summary_to_payload,
)

__all__ = [
    "ANALYSIS_SETTINGS_FIELDS",
    "ScalarSettingValue",
    "ScalarSettings",
    "analysis_settings_snapshot_from_mapping",
    "analysis_settings_snapshot_items",
    "analysis_settings_snapshot_to_metadata",
    "driving_phase_summary_from_mapping",
    "driving_phase_summary_to_payload",
    "finding_evidence_from_mapping",
    "sanitize_analysis_settings",
    "speed_profile_summary_from_mapping",
    "speed_profile_summary_to_payload",
    "strength_metrics_from_mapping",
    "strength_peak_from_mapping",
    "strength_peak_payloads",
    "strength_peak_to_payload",
    "strength_peaks_from_sequence",
]
