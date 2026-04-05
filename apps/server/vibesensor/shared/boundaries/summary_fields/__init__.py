"""Canonical boundary package for analysis-summary field fragments."""

from .evidence_metrics import build_evidence_metrics
from .finding import (
    finding_from_payload,
    finding_payload_from_domain,
    matched_point_from_observation,
)
from .hotspot import (
    location_intensity_summaries_from_rows,
    location_intensity_summary_from_mapping,
    phase_intensity_summary_from_mapping,
    strength_bucket_distribution_from_mapping,
)
from .order_match import (
    order_match_observation_from_mapping,
    order_match_observations_from_sequence,
)
from .origin import (
    SuspectedVibrationOrigin,
    build_origin_explanation,
    location_hotspot_from_payload,
    origin_payload_from_finding,
    vibration_origin_from_payload,
)
from .test_plan import step_payload_from_action, step_payloads_from_plan
from .warnings import localize_warning_list, summary_warning_payload, summary_warning_payloads

__all__ = [
    "SuspectedVibrationOrigin",
    "build_evidence_metrics",
    "build_origin_explanation",
    "finding_from_payload",
    "finding_payload_from_domain",
    "localize_warning_list",
    "location_hotspot_from_payload",
    "location_intensity_summaries_from_rows",
    "location_intensity_summary_from_mapping",
    "matched_point_from_observation",
    "order_match_observation_from_mapping",
    "order_match_observations_from_sequence",
    "origin_payload_from_finding",
    "phase_intensity_summary_from_mapping",
    "step_payload_from_action",
    "step_payloads_from_plan",
    "strength_bucket_distribution_from_mapping",
    "summary_warning_payload",
    "summary_warning_payloads",
    "vibration_origin_from_payload",
]
