"""Build FindingEvidenceMetrics payloads from domain Finding + FindingEvidence."""

from __future__ import annotations

from vibesensor.domain import Finding, FindingEvidence
from vibesensor.shared.types.analysis_views import FindingEvidenceMetrics


def build_evidence_metrics(
    finding: Finding,
) -> FindingEvidenceMetrics | None:
    """Build evidence metrics payload from a domain Finding.

    Returns the fully populated ``FindingEvidenceMetrics`` dict when evidence
    exists, a minimal dict with only ``vibration_strength_db`` when the finding
    carries strength but no evidence, or ``None`` when neither is present.
    """
    if finding.evidence is not None:
        return _metrics_from_evidence(finding.evidence, finding)
    if finding.vibration_strength_db is not None:
        return {"vibration_strength_db": finding.vibration_strength_db}
    return None


def _metrics_from_evidence(
    ev: FindingEvidence,
    finding: Finding,
) -> FindingEvidenceMetrics:
    metrics: FindingEvidenceMetrics = {
        "match_rate": ev.match_rate,
        "presence_ratio": ev.presence_ratio,
        "burstiness": ev.burstiness,
        "spatial_concentration": ev.spatial_concentration,
        "frequency_correlation": ev.frequency_correlation,
        "speed_uniformity": ev.speed_uniformity,
        "spatial_uniformity": ev.spatial_uniformity,
    }
    if ev.global_match_rate is not None:
        metrics["global_match_rate"] = ev.global_match_rate
    if ev.focused_speed_band is not None:
        metrics["focused_speed_band"] = ev.focused_speed_band
    if ev.mean_relative_error is not None:
        metrics["mean_relative_error"] = ev.mean_relative_error
    if ev.mean_noise_floor_db is not None:
        metrics["mean_noise_floor_db"] = ev.mean_noise_floor_db
    if ev.possible_samples is not None:
        metrics["possible_samples"] = ev.possible_samples
    if ev.matched_samples is not None:
        metrics["matched_samples"] = ev.matched_samples
    if ev.snr_db is not None:
        metrics["snr_db"] = ev.snr_db
    if ev.vibration_strength_db is not None:
        metrics["vibration_strength_db"] = ev.vibration_strength_db
    elif finding.vibration_strength_db is not None:
        metrics["vibration_strength_db"] = finding.vibration_strength_db
    if ev.phases_with_evidence is not None:
        metrics["phases_with_evidence"] = ev.phases_with_evidence
    if ev.phase_confidences:
        metrics["per_phase_confidence"] = dict(ev.phase_confidences)
    return metrics
