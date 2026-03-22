"""Final DomainFinding construction for matched tracked-order findings."""

from __future__ import annotations

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain import (
    FindingEvidence,
    FindingKind,
    VibrationOrigin,
)
from vibesensor.shared.constants import MEMS_NOISE_FLOOR_G
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.use_cases.diagnostics.order_matching import OrderMatchAccumulator
from vibesensor.use_cases.diagnostics.order_scoring import (
    OrderFindingBuildContext,
    OrderFindingScore,
)
from vibesensor.use_cases.diagnostics.order_statistics import (
    compute_matched_speed_phase_evidence,
)
from vibesensor.use_cases.diagnostics.rotational_physics import (
    OrderHypothesis,
    _order_label,
)
from vibesensor.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)


def assemble_order_finding(
    hypothesis: OrderHypothesis,
    match: OrderMatchAccumulator,
    *,
    context: OrderFindingBuildContext,
    score: OrderFindingScore,
) -> tuple[float, DomainFinding]:
    """Build a single order finding from a scored match result."""
    ref_text = ", ".join(sorted(match.ref_sources))
    evidence = i18n_ref(
        "EVIDENCE_ORDER_TRACKED",
        order_label=_order_label(hypothesis.order, hypothesis.order_label_base),
        matched=match.matched,
        possible=match.possible,
        match_rate=context.effective_match_rate,
        mean_rel_err=score.mean_relative_error,
        ref_text=ref_text,
    )
    if score.location_line:
        evidence = dict(evidence)
        evidence["_suffix"] = f" {score.location_line}"

    (
        _peak_speed_kmh,
        _speed_window_kmh,
        strongest_speed_band,
        phase_evidence,
        dominant_phase,
    ) = compute_matched_speed_phase_evidence(
        match.matched_points,
        focused_speed_band=context.focused_speed_band,
        hotspot_speed_band=score.hotspot_speed_band,
    )
    phases_raw = phase_evidence.get("phases_detected")
    phases_detected = tuple(phases_raw) if isinstance(phases_raw, list) else ()
    finding = DomainFinding(
        finding_id="F_ORDER",
        finding_key=hypothesis.key,
        suspected_source=hypothesis.suspected_source,
        confidence=score.confidence,
        order=_order_label(hypothesis.order, hypothesis.order_label_base),
        strongest_location=score.strongest_location or None,
        strongest_speed_band=strongest_speed_band or None,
        kind=FindingKind.DIAGNOSTIC,
        dominant_phase=dominant_phase,
        ranking_score=score.ranking_score,
        dominance_ratio=score.dominance_ratio,
        diffuse_excitation=score.diffuse_excitation,
        weak_spatial_separation=score.weak_spatial_separation,
        vibration_strength_db=score.absolute_strength_db,
        cruise_fraction=_as_float(phase_evidence["cruise_fraction"]) or 0.0,
        phases_detected=phases_detected,
        matched_points=tuple(match.matched_points),
        evidence=FindingEvidence(
            match_rate=context.effective_match_rate,
            global_match_rate=context.match_rate,
            focused_speed_band=context.focused_speed_band,
            mean_relative_error=score.mean_relative_error,
            mean_noise_floor_db=canonical_vibration_db(
                peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, score.mean_floor),
                floor_amp_g=MEMS_NOISE_FLOOR_G,
            ),
            possible_samples=match.possible,
            matched_samples=match.matched,
            frequency_correlation=score.frequency_correlation,
            phases_with_evidence=score.phases_with_evidence,
            phase_confidences=(
                tuple(sorted(score.per_phase_confidence.items()))
                if score.per_phase_confidence
                else ()
            ),
            vibration_strength_db=score.absolute_strength_db,
        ),
        location=score.domain_hotspot,
        origin=VibrationOrigin.from_analysis_inputs(
            suspected_source=hypothesis.suspected_source,
            hotspot=score.domain_hotspot,
            dominance_ratio=score.dominance_ratio,
            speed_band=strongest_speed_band or None,
            dominant_phase=dominant_phase,
        ),
    )
    return score.ranking_score, finding
