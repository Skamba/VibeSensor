"""Support helpers for the findings builder orchestration layer."""

from __future__ import annotations

from collections.abc import Sequence

from ..constants import ORDER_SUPPRESS_PERSISTENT_MIN_CONF, SPEED_COVERAGE_MIN_PCT
from ..domain_models import as_float_or_none as _as_float
from ._types import Finding, JsonValue, MetadataDict, PhaseLabels, Sample
from .helpers import _effective_engine_rpm
from .order_analysis import _i18n_ref
from .phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    segment_run_phases,
)
from .ranking import finding_sort_key

_MIN_DIAGNOSTIC_SAMPLES = 5

_REF_MISSING: dict[str, str] = {"_i18n_key": "REFERENCE_MISSING"}
_REF_MISSING_AMPLITUDE: dict[str, str] = {
    "_i18n_key": "REFERENCE_MISSING_ORDER_SPECIFIC_AMPLITUDE_RANKING_SKIPPED",
}


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: str,
    evidence_summary: JsonValue,
    quick_checks: list[JsonValue],
) -> Finding:
    return {
        "finding_id": finding_id,
        "finding_type": "reference",
        "suspected_source": suspected_source,
        "evidence_summary": evidence_summary,
        "frequency_hz_or_order": {**_REF_MISSING},
        "amplitude_metric": {
            "name": "not_available",
            "value": None,
            "units": "n/a",
            "definition": {**_REF_MISSING_AMPLITUDE},
        },
        "confidence_0_to_1": None,
        "quick_checks": quick_checks[:3],
    }


def build_reference_findings(
    *,
    metadata: MetadataDict,
    samples: list[Sample],
    speed_sufficient: bool,
    speed_non_null_pct: float,
    tire_circumference_m: float | None,
    raw_sample_rate_hz: float | None,
) -> tuple[list[Finding], bool]:
    """Build reference-missing findings and return engine reference sufficiency."""
    findings: list[Finding] = []
    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source="unknown",
                evidence_summary=_i18n_ref(
                    "VEHICLE_SPEED_COVERAGE_IS_SPEED_NON_NULL_PCT",
                    speed_non_null_pct=speed_non_null_pct,
                    threshold=SPEED_COVERAGE_MIN_PCT,
                ),
                quick_checks=[
                    _i18n_ref("RECORD_VEHICLE_SPEED_FOR_MOST_SAMPLES_GPS_OR"),
                    _i18n_ref("VERIFY_TIMESTAMP_ALIGNMENT_BETWEEN_SPEED_AND_ACCELERATION_STREAM"),
                ],
            ),
        )

    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source="wheel/tire",
                evidence_summary=_i18n_ref(
                    "VEHICLE_SPEED_IS_AVAILABLE_BUT_TIRE_CIRCUMFERENCE_REFERENCE",
                ),
                quick_checks=[
                    _i18n_ref("PROVIDE_TIRE_CIRCUMFERENCE_OR_TIRE_SIZE_WIDTH_ASPECT"),
                    _i18n_ref("RE_RUN_WITH_MEASURED_LOADED_TIRE_CIRCUMFERENCE"),
                ],
            ),
        )

    engine_ref_sufficient = has_engine_reference(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    if not engine_ref_sufficient:
        engine_rpm_non_null_pct = engine_reference_coverage_pct(
            samples,
            metadata=metadata,
            tire_circumference_m=tire_circumference_m,
        )
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source="engine",
                evidence_summary=_i18n_ref(
                    "ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON",
                    engine_rpm_non_null_pct=engine_rpm_non_null_pct,
                ),
                quick_checks=[
                    _i18n_ref("LOG_ENGINE_RPM_FROM_CAN_OBD_FOR_THE"),
                    _i18n_ref("KEEP_TIMESTAMP_BASE_SHARED_WITH_ACCELEROMETER_AND_SPEED"),
                ],
            ),
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source="unknown",
                evidence_summary=_i18n_ref("RAW_ACCELEROMETER_SAMPLE_RATE_IS_MISSING_SO_DOMINANT"),
                quick_checks=[_i18n_ref("RECORD_THE_TRUE_ACCELEROMETER_SAMPLE_RATE_IN_RUN")],
            ),
        )
    return findings, engine_ref_sufficient


def engine_reference_coverage_pct(
    samples: list[Sample],
    *,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
) -> float:
    """Compute engine reference coverage percentage from samples and metadata."""
    engine_ref_count = sum(
        1
        for sample in samples
        if ((_effective_engine_rpm(sample, metadata, tire_circumference_m))[0] or 0) > 0
    )
    return (engine_ref_count / len(samples) * 100.0) if samples else 0.0


def has_engine_reference(
    samples: list[Sample],
    *,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
) -> bool:
    """Return whether the engine reference coverage is sufficient."""
    pct: float = engine_reference_coverage_pct(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    return bool(pct >= SPEED_COVERAGE_MIN_PCT)


def prepare_analysis_samples(
    samples: list[Sample],
    *,
    per_sample_phases: PhaseLabels | None,
) -> tuple[list[Sample], Sequence[DrivingPhase], list[DrivingPhase], bool]:
    """Prepare filtered samples and aligned phase labels for findings analysis."""
    if per_sample_phases is not None and len(per_sample_phases) == len(samples):
        resolved_phases: list[DrivingPhase] = [
            phase if isinstance(phase, DrivingPhase) else DrivingPhase(str(phase))
            for phase in per_sample_phases
        ]
    else:
        resolved_phases, _ = segment_run_phases(samples)

    diagnostic_mask = diagnostic_sample_mask(resolved_phases)
    diagnostic_samples = [
        sample for sample, keep in zip(samples, diagnostic_mask, strict=True) if keep
    ]
    use_filtered_samples = len(diagnostic_samples) >= _MIN_DIAGNOSTIC_SAMPLES
    analysis_samples = diagnostic_samples if use_filtered_samples else samples
    if analysis_samples is diagnostic_samples:
        analysis_phases: Sequence[DrivingPhase] = [
            phase for phase, keep in zip(resolved_phases, diagnostic_mask, strict=True) if keep
        ]
    else:
        analysis_phases = list(resolved_phases)
    return analysis_samples, analysis_phases, resolved_phases, use_filtered_samples


def collect_order_frequencies(order_findings: list[Finding]) -> set[float]:
    """Collect matched order frequencies used to suppress duplicate persistent findings."""
    order_freqs: set[float] = set()
    for order_finding in order_findings:
        if (
            _as_float(order_finding.get("confidence_0_to_1")) or 0.0
        ) < ORDER_SUPPRESS_PERSISTENT_MIN_CONF:
            continue
        points = order_finding.get("matched_points")
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            matched_hz = _as_float(point.get("matched_hz"))
            if matched_hz is not None and matched_hz > 0:
                order_freqs.add(matched_hz)
    return order_freqs


def finalize_findings(findings: list[Finding]) -> list[Finding]:
    """Partition, rank, and assign stable public finding IDs."""
    reference_findings: list[Finding] = []
    diagnostic_findings: list[Finding] = []
    informational_findings: list[Finding] = []
    for item in findings:
        finding_id = str(item.get("finding_id", ""))
        if finding_id.startswith("REF_"):
            reference_findings.append(item)
        elif str(item.get("severity") or "").strip().lower() == "info":
            informational_findings.append(item)
        else:
            diagnostic_findings.append(item)

    diagnostic_findings.sort(key=finding_sort_key, reverse=True)
    informational_findings.sort(key=finding_sort_key, reverse=True)
    ordered_findings = reference_findings + diagnostic_findings + informational_findings
    diag_counter = 0
    for finding in ordered_findings:
        finding_id = str(finding.get("finding_id", "")).strip()
        if not finding_id.startswith("REF_"):
            diag_counter += 1
            finding["finding_id"] = f"F{diag_counter:03d}"
    return ordered_findings
