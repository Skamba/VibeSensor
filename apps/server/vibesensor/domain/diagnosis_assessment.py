"""Canonical whole-run diagnosis assessment policy and typed results."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from .finding import Finding

__all__ = [
    "DIAGNOSIS_AMBIGUOUS_SCORE_GAP",
    "DIAGNOSIS_CLOSE_ALTERNATIVE_REEVALUATION_GAP",
    "DiagnosisAssessment",
    "DiagnosisAssessmentFactor",
    "DiagnosisAssessmentFactorDetails",
    "DiagnosisAssessmentInputs",
    "apply_diagnosis_assessment_fallback",
    "diagnosis_assessment_from_components",
    "score_diagnosis_assessment_inputs",
]

DIAGNOSIS_CLOSE_ALTERNATIVE_REEVALUATION_GAP = 0.10
DIAGNOSIS_AMBIGUOUS_SCORE_GAP = 0.05
_DIAGNOSIS_SUSPICIOUS_CAVEAT_KEYS = frozenset(
    {
        "drifting_frequency",
        "mixed_support_locations",
        "weak_spatial",
        "close_alternative",
    }
)


@dataclass(frozen=True, slots=True)
class DiagnosisAssessmentFactorDetails:
    """Structured details carried by one diagnosis support/counterevidence factor."""

    raw_backed_sample_count: int | None = None
    supporting_window_count: int | None = None
    supporting_duration_s: float | None = None
    stable_frequency_min_hz: float | None = None
    stable_frequency_max_hz: float | None = None
    frequency_span_hz: float | None = None
    supporting_location_count: int | None = None
    top_support_location: str | None = None
    top_support_share: float | None = None
    mean_relative_error: float | None = None
    snr_db: float | None = None
    alternative_source: str | None = None
    speed_gap_window_count: int | None = None
    rpm_gap_window_count: int | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosisAssessmentFactor:
    """One stable diagnosis support or counterevidence factor."""

    factor_key: str
    polarity: str
    severity: str
    weight: float
    details: DiagnosisAssessmentFactorDetails = field(
        default_factory=DiagnosisAssessmentFactorDetails
    )


@dataclass(frozen=True, slots=True)
class DiagnosisAssessmentInputs:
    """Normalized canonical inputs for whole-run diagnosis scoring."""

    base_confidence: float
    data_basis: str
    raw_backed_sample_count: int
    supporting_window_count: int | None
    supporting_duration_s: float | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    supporting_location_count: int
    top_support_location: str | None
    top_support_share: float | None
    mean_relative_error: float | None
    snr_db: float | None
    alternative_source: str | None
    has_reference_gap: bool
    weak_spatial: bool
    context_traceable: bool
    context_source: str
    speed_gap_window_count: int
    rpm_gap_window_count: int
    confidence_gap_to_alternative: float | None = None


@dataclass(frozen=True, slots=True)
class DiagnosisAssessment:
    """Canonical diagnosis confidence, factors, ambiguity, and caveats."""

    score_0_to_1: float
    label_key: str
    pct_text: str
    tier: str
    data_basis: str
    raw_backed_sample_count: int
    supporting_window_count: int | None
    supporting_duration_s: float | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    supporting_location_count: int
    top_support_location: str | None
    top_support_share: float | None
    mean_relative_error: float | None
    snr_db: float | None
    alternative_source: str | None
    has_reference_gap: bool
    speed_gap_window_count: int
    rpm_gap_window_count: int
    uses_summary_fallback: bool
    fallback_reason: str | None
    signal_keys: tuple[str, ...]
    caveat_keys: tuple[str, ...]
    support_factors: tuple[DiagnosisAssessmentFactor, ...] = ()
    counterevidence_factors: tuple[DiagnosisAssessmentFactor, ...] = ()
    confidence_gap_to_alternative: float | None = None
    ambiguous_diagnosis: bool = False
    suspicious: bool = False


def score_diagnosis_assessment_inputs(inputs: DiagnosisAssessmentInputs) -> DiagnosisAssessment:
    """Apply the canonical whole-run diagnosis scoring policy."""

    score = max(0.0, min(0.70, 0.25 + (inputs.base_confidence * 0.40)))
    signal_keys: list[str] = []
    caveat_keys: list[str] = []
    frequency_span_hz = _frequency_span_hz(
        stable_frequency_min_hz=inputs.stable_frequency_min_hz,
        stable_frequency_max_hz=inputs.stable_frequency_max_hz,
    )

    if inputs.data_basis == "raw_backed":
        score += 0.10
        signal_keys.append("raw_backed")
    elif inputs.data_basis == "partial_raw_backed":
        score += 0.05
        signal_keys.append("raw_backed")
        caveat_keys.append("raw_replay_incomplete")
    else:
        score -= 0.05
        caveat_keys.append("summary_only")

    if inputs.context_traceable:
        if inputs.context_source == "legacy":
            score -= 0.05
            caveat_keys.append("legacy_context")
        else:
            if inputs.speed_gap_window_count > 0:
                score -= 0.04
                caveat_keys.append("speed_context_gaps")
            if inputs.rpm_gap_window_count > 0:
                score -= 0.04
                caveat_keys.append("rpm_context_gaps")

    if inputs.supporting_window_count is not None:
        if inputs.supporting_window_count >= 4:
            score += 0.10
            signal_keys.append("repeated_support")
        elif inputs.supporting_window_count >= 2:
            score += 0.05
            signal_keys.append("repeated_support")
        elif inputs.supporting_window_count <= 1:
            score -= 0.10
            caveat_keys.append("sparse_support")

    if inputs.supporting_duration_s is not None:
        if inputs.supporting_duration_s >= 1.0:
            score += 0.08
            signal_keys.append("sustained_support")
        elif inputs.supporting_duration_s >= 0.5:
            score += 0.04
            signal_keys.append("sustained_support")
        elif inputs.supporting_duration_s > 0:
            score -= 0.06
            caveat_keys.append("brief_support")

    if frequency_span_hz is not None:
        if frequency_span_hz <= 0.5:
            score += 0.08
            signal_keys.append("stable_frequency")
        elif frequency_span_hz <= 1.0:
            score += 0.04
            signal_keys.append("stable_frequency")
        elif frequency_span_hz > 1.5:
            score -= 0.06
            caveat_keys.append("drifting_frequency")

    if inputs.mean_relative_error is not None:
        if inputs.mean_relative_error <= 0.05:
            score += 0.08
            signal_keys.append("tight_order_lock")
        elif inputs.mean_relative_error >= 0.15:
            score -= 0.08
            caveat_keys.append("loose_order_lock")

    if inputs.top_support_share is not None:
        if inputs.top_support_share >= 0.67:
            score += 0.08
            signal_keys.append("localized_support")
        elif inputs.supporting_location_count > 1 and inputs.top_support_share < 0.55:
            score -= 0.10
            caveat_keys.append("mixed_support_locations")

    if inputs.snr_db is not None:
        if inputs.snr_db >= 6.0:
            score += 0.05
            signal_keys.append("clean_signal")
        elif inputs.snr_db < 3.0:
            score -= 0.06
            caveat_keys.append("noisy_signal")

    if inputs.weak_spatial:
        score -= 0.10
        caveat_keys.append("weak_spatial")

    if inputs.alternative_source is not None:
        score -= 0.10
        caveat_keys.append("close_alternative")

    if inputs.has_reference_gap:
        score -= 0.06
        caveat_keys.append("incomplete_reference")

    return _assessment_from_keys(
        score_0_to_1=_rounded_score(score),
        data_basis=inputs.data_basis,
        raw_backed_sample_count=inputs.raw_backed_sample_count,
        supporting_window_count=inputs.supporting_window_count,
        supporting_duration_s=inputs.supporting_duration_s,
        stable_frequency_min_hz=inputs.stable_frequency_min_hz,
        stable_frequency_max_hz=inputs.stable_frequency_max_hz,
        supporting_location_count=inputs.supporting_location_count,
        top_support_location=inputs.top_support_location,
        top_support_share=inputs.top_support_share,
        mean_relative_error=inputs.mean_relative_error,
        snr_db=inputs.snr_db,
        alternative_source=inputs.alternative_source,
        has_reference_gap=inputs.has_reference_gap,
        speed_gap_window_count=inputs.speed_gap_window_count,
        rpm_gap_window_count=inputs.rpm_gap_window_count,
        uses_summary_fallback=False,
        fallback_reason=None,
        signal_keys=tuple(dict.fromkeys(signal_keys)),
        caveat_keys=tuple(dict.fromkeys(caveat_keys)),
        confidence_gap_to_alternative=inputs.confidence_gap_to_alternative,
    )


def apply_diagnosis_assessment_fallback(
    assessment: DiagnosisAssessment,
    *,
    fallback_reason: str,
) -> DiagnosisAssessment:
    """Mark an assessment as an explicit fallback and rebuild its factor rows."""

    caveat_keys = list(assessment.caveat_keys)
    if assessment.data_basis == "summary_only" and "summary_only" not in caveat_keys:
        caveat_keys.append("summary_only")
    if assessment.data_basis == "partial_raw_backed" and "raw_replay_incomplete" not in caveat_keys:
        caveat_keys.append("raw_replay_incomplete")
    return _assessment_from_keys(
        score_0_to_1=assessment.score_0_to_1,
        data_basis=assessment.data_basis,
        raw_backed_sample_count=assessment.raw_backed_sample_count,
        supporting_window_count=assessment.supporting_window_count,
        supporting_duration_s=assessment.supporting_duration_s,
        stable_frequency_min_hz=assessment.stable_frequency_min_hz,
        stable_frequency_max_hz=assessment.stable_frequency_max_hz,
        supporting_location_count=assessment.supporting_location_count,
        top_support_location=assessment.top_support_location,
        top_support_share=assessment.top_support_share,
        mean_relative_error=assessment.mean_relative_error,
        snr_db=assessment.snr_db,
        alternative_source=assessment.alternative_source,
        has_reference_gap=assessment.has_reference_gap,
        speed_gap_window_count=assessment.speed_gap_window_count,
        rpm_gap_window_count=assessment.rpm_gap_window_count,
        uses_summary_fallback=True,
        fallback_reason=fallback_reason,
        signal_keys=assessment.signal_keys,
        caveat_keys=tuple(dict.fromkeys(caveat_keys)),
        confidence_gap_to_alternative=assessment.confidence_gap_to_alternative,
        ambiguous_diagnosis=assessment.ambiguous_diagnosis,
        suspicious=assessment.suspicious,
    )


def diagnosis_assessment_from_components(
    *,
    score_0_to_1: float,
    data_basis: str,
    raw_backed_sample_count: int,
    supporting_window_count: int | None,
    supporting_duration_s: float | None,
    stable_frequency_min_hz: float | None,
    stable_frequency_max_hz: float | None,
    supporting_location_count: int,
    top_support_location: str | None,
    top_support_share: float | None,
    mean_relative_error: float | None,
    snr_db: float | None,
    alternative_source: str | None,
    has_reference_gap: bool,
    speed_gap_window_count: int,
    rpm_gap_window_count: int,
    uses_summary_fallback: bool,
    fallback_reason: str | None,
    support_factors: tuple[DiagnosisAssessmentFactor, ...],
    counterevidence_factors: tuple[DiagnosisAssessmentFactor, ...],
    confidence_gap_to_alternative: float | None = None,
    ambiguous_diagnosis: bool | None = None,
    suspicious: bool | None = None,
) -> DiagnosisAssessment:
    """Build an assessment from persisted or externally supplied factor rows."""

    label_key = _label_key_for_score(score_0_to_1)
    signal_keys = tuple(factor.factor_key for factor in support_factors)
    caveat_keys = tuple(factor.factor_key for factor in counterevidence_factors)
    derived_ambiguous = (
        confidence_gap_to_alternative is not None
        and confidence_gap_to_alternative <= DIAGNOSIS_AMBIGUOUS_SCORE_GAP
    )
    derived_suspicious = derived_ambiguous or any(
        factor.factor_key in _DIAGNOSIS_SUSPICIOUS_CAVEAT_KEYS for factor in counterevidence_factors
    )
    return DiagnosisAssessment(
        score_0_to_1=score_0_to_1,
        label_key=label_key,
        pct_text=f"{score_0_to_1 * 100:.0f}%",
        tier=_tier_for_score(
            label_key=label_key,
            score_0_to_1=score_0_to_1,
            caveat_keys=caveat_keys,
        ),
        data_basis=data_basis,
        raw_backed_sample_count=raw_backed_sample_count,
        supporting_window_count=supporting_window_count,
        supporting_duration_s=supporting_duration_s,
        stable_frequency_min_hz=stable_frequency_min_hz,
        stable_frequency_max_hz=stable_frequency_max_hz,
        supporting_location_count=supporting_location_count,
        top_support_location=top_support_location,
        top_support_share=top_support_share,
        mean_relative_error=mean_relative_error,
        snr_db=snr_db,
        alternative_source=alternative_source,
        has_reference_gap=has_reference_gap,
        speed_gap_window_count=speed_gap_window_count,
        rpm_gap_window_count=rpm_gap_window_count,
        uses_summary_fallback=uses_summary_fallback,
        fallback_reason=fallback_reason,
        signal_keys=signal_keys,
        caveat_keys=caveat_keys,
        support_factors=support_factors,
        counterevidence_factors=counterevidence_factors,
        confidence_gap_to_alternative=confidence_gap_to_alternative,
        ambiguous_diagnosis=(
            ambiguous_diagnosis if ambiguous_diagnosis is not None else derived_ambiguous
        ),
        suspicious=suspicious if suspicious is not None else derived_suspicious,
    )


def _assessment_from_keys(
    *,
    score_0_to_1: float,
    data_basis: str,
    raw_backed_sample_count: int,
    supporting_window_count: int | None,
    supporting_duration_s: float | None,
    stable_frequency_min_hz: float | None,
    stable_frequency_max_hz: float | None,
    supporting_location_count: int,
    top_support_location: str | None,
    top_support_share: float | None,
    mean_relative_error: float | None,
    snr_db: float | None,
    alternative_source: str | None,
    has_reference_gap: bool,
    speed_gap_window_count: int,
    rpm_gap_window_count: int,
    uses_summary_fallback: bool,
    fallback_reason: str | None,
    signal_keys: tuple[str, ...],
    caveat_keys: tuple[str, ...],
    confidence_gap_to_alternative: float | None,
    ambiguous_diagnosis: bool | None = None,
    suspicious: bool | None = None,
) -> DiagnosisAssessment:
    assessment = DiagnosisAssessment(
        score_0_to_1=score_0_to_1,
        label_key=_label_key_for_score(score_0_to_1),
        pct_text=f"{score_0_to_1 * 100:.0f}%",
        tier=_tier_for_score(
            label_key=_label_key_for_score(score_0_to_1),
            score_0_to_1=score_0_to_1,
            caveat_keys=caveat_keys,
        ),
        data_basis=data_basis,
        raw_backed_sample_count=raw_backed_sample_count,
        supporting_window_count=supporting_window_count,
        supporting_duration_s=supporting_duration_s,
        stable_frequency_min_hz=stable_frequency_min_hz,
        stable_frequency_max_hz=stable_frequency_max_hz,
        supporting_location_count=supporting_location_count,
        top_support_location=top_support_location,
        top_support_share=top_support_share,
        mean_relative_error=mean_relative_error,
        snr_db=snr_db,
        alternative_source=alternative_source,
        has_reference_gap=has_reference_gap,
        speed_gap_window_count=speed_gap_window_count,
        rpm_gap_window_count=rpm_gap_window_count,
        uses_summary_fallback=uses_summary_fallback,
        fallback_reason=fallback_reason,
        signal_keys=signal_keys,
        caveat_keys=caveat_keys,
        confidence_gap_to_alternative=confidence_gap_to_alternative,
        ambiguous_diagnosis=False,
        suspicious=False,
    )
    support_factors = tuple(_support_factor(key, assessment) for key in signal_keys)
    counterevidence_factors = tuple(_counterevidence_factor(key, assessment) for key in caveat_keys)
    return diagnosis_assessment_from_components(
        score_0_to_1=score_0_to_1,
        data_basis=data_basis,
        raw_backed_sample_count=raw_backed_sample_count,
        supporting_window_count=supporting_window_count,
        supporting_duration_s=supporting_duration_s,
        stable_frequency_min_hz=stable_frequency_min_hz,
        stable_frequency_max_hz=stable_frequency_max_hz,
        supporting_location_count=supporting_location_count,
        top_support_location=top_support_location,
        top_support_share=top_support_share,
        mean_relative_error=mean_relative_error,
        snr_db=snr_db,
        alternative_source=alternative_source,
        has_reference_gap=has_reference_gap,
        speed_gap_window_count=speed_gap_window_count,
        rpm_gap_window_count=rpm_gap_window_count,
        uses_summary_fallback=uses_summary_fallback,
        fallback_reason=fallback_reason,
        support_factors=support_factors,
        counterevidence_factors=counterevidence_factors,
        confidence_gap_to_alternative=confidence_gap_to_alternative,
        ambiguous_diagnosis=ambiguous_diagnosis,
        suspicious=suspicious,
    )


def _support_factor(
    factor_key: str,
    assessment: DiagnosisAssessment,
) -> DiagnosisAssessmentFactor:
    return DiagnosisAssessmentFactor(
        factor_key=factor_key,
        polarity="support",
        severity=_factor_severity(_support_factor_weight(factor_key, assessment)),
        weight=_support_factor_weight(factor_key, assessment),
        details=_factor_details(factor_key, assessment),
    )


def _counterevidence_factor(
    factor_key: str,
    assessment: DiagnosisAssessment,
) -> DiagnosisAssessmentFactor:
    return DiagnosisAssessmentFactor(
        factor_key=factor_key,
        polarity="counterevidence",
        severity=_factor_severity(_counter_factor_weight(factor_key)),
        weight=_counter_factor_weight(factor_key),
        details=_factor_details(factor_key, assessment),
    )


def _factor_severity(weight: float) -> str:
    if weight >= 0.10:
        return "high"
    if weight >= 0.07:
        return "medium"
    return "low"


def _support_factor_weight(factor_key: str, assessment: DiagnosisAssessment) -> float:
    if factor_key == "raw_backed":
        if assessment.data_basis == "partial_raw_backed":
            return 0.05
        return 0.10
    if factor_key == "repeated_support":
        if (
            assessment.supporting_window_count is not None
            and assessment.supporting_window_count >= 4
        ):
            return 0.10
        return 0.05
    if factor_key == "sustained_support":
        if assessment.supporting_duration_s is not None and assessment.supporting_duration_s >= 1.0:
            return 0.08
        return 0.04
    if factor_key == "stable_frequency":
        frequency_span_hz = _frequency_span_hz(
            stable_frequency_min_hz=assessment.stable_frequency_min_hz,
            stable_frequency_max_hz=assessment.stable_frequency_max_hz,
        )
        if frequency_span_hz is not None and frequency_span_hz <= 0.5:
            return 0.08
        return 0.04
    if factor_key == "tight_order_lock":
        return 0.08
    if factor_key == "localized_support":
        return 0.08
    if factor_key == "clean_signal":
        return 0.05
    raise ValueError(f"unsupported support factor key: {factor_key}")


def _counter_factor_weight(factor_key: str) -> float:
    if factor_key in {"summary_only", "legacy_context", "raw_replay_incomplete"}:
        return 0.05
    if factor_key in {"speed_context_gaps", "rpm_context_gaps"}:
        return 0.04
    if factor_key in {
        "brief_support",
        "drifting_frequency",
        "noisy_signal",
        "incomplete_reference",
    }:
        return 0.06
    if factor_key in {
        "sparse_support",
        "loose_order_lock",
        "mixed_support_locations",
        "weak_spatial",
        "close_alternative",
    }:
        return 0.10 if factor_key != "loose_order_lock" else 0.08
    raise ValueError(f"unsupported counterevidence factor key: {factor_key}")


def _factor_details(
    factor_key: str,
    assessment: DiagnosisAssessment,
) -> DiagnosisAssessmentFactorDetails:
    details = DiagnosisAssessmentFactorDetails()
    if factor_key == "raw_backed":
        return replace(details, raw_backed_sample_count=assessment.raw_backed_sample_count)
    if factor_key in {"repeated_support", "sparse_support"}:
        return replace(details, supporting_window_count=assessment.supporting_window_count)
    if factor_key in {"sustained_support", "brief_support"}:
        return replace(details, supporting_duration_s=assessment.supporting_duration_s)
    if factor_key in {"stable_frequency", "drifting_frequency"}:
        return replace(
            details,
            stable_frequency_min_hz=assessment.stable_frequency_min_hz,
            stable_frequency_max_hz=assessment.stable_frequency_max_hz,
            frequency_span_hz=_frequency_span_hz(
                stable_frequency_min_hz=assessment.stable_frequency_min_hz,
                stable_frequency_max_hz=assessment.stable_frequency_max_hz,
            ),
        )
    if factor_key in {"tight_order_lock", "loose_order_lock"}:
        return replace(details, mean_relative_error=assessment.mean_relative_error)
    if factor_key in {"localized_support", "mixed_support_locations"}:
        return replace(
            details,
            supporting_location_count=assessment.supporting_location_count,
            top_support_location=assessment.top_support_location,
            top_support_share=assessment.top_support_share,
        )
    if factor_key in {"clean_signal", "noisy_signal"}:
        return replace(details, snr_db=assessment.snr_db)
    if factor_key == "close_alternative":
        return replace(details, alternative_source=assessment.alternative_source)
    if factor_key == "speed_context_gaps":
        return replace(details, speed_gap_window_count=assessment.speed_gap_window_count)
    if factor_key == "rpm_context_gaps":
        return replace(details, rpm_gap_window_count=assessment.rpm_gap_window_count)
    if factor_key == "summary_only" and assessment.uses_summary_fallback:
        return replace(details, fallback_reason=assessment.fallback_reason)
    return details


def _rounded_score(score: float) -> float:
    bounded = max(0.10, min(0.90, score))
    return round(bounded / 0.05) * 0.05


def _label_key_for_score(score: float) -> str:
    if score >= Finding.CONFIDENCE_HIGH_THRESHOLD:
        return "CONFIDENCE_HIGH"
    if score >= Finding.CONFIDENCE_MEDIUM_THRESHOLD:
        return "CONFIDENCE_MEDIUM"
    return "CONFIDENCE_LOW"


def _tier_for_score(*, label_key: str, score_0_to_1: float, caveat_keys: tuple[str, ...]) -> str:
    if label_key == "CONFIDENCE_LOW":
        return "A"
    if score_0_to_1 < Finding.CONFIDENCE_HIGH_THRESHOLD:
        return "B"
    if set(caveat_keys).intersection(
        {
            "summary_only",
            "raw_replay_incomplete",
            "drifting_frequency",
            "loose_order_lock",
            "mixed_support_locations",
            "weak_spatial",
            "close_alternative",
            "incomplete_reference",
            "legacy_context",
            "speed_context_gaps",
            "rpm_context_gaps",
            "noisy_signal",
        }
    ):
        return "B"
    return "C"


def _frequency_span_hz(
    *,
    stable_frequency_min_hz: float | None,
    stable_frequency_max_hz: float | None,
) -> float | None:
    if stable_frequency_min_hz is None or stable_frequency_max_hz is None:
        return None
    span = stable_frequency_max_hz - stable_frequency_min_hz
    return span if math.isfinite(span) and span >= 0 else None
