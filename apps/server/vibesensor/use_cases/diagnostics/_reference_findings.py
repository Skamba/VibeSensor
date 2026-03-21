"""Reference-finding helpers for diagnostics orchestration."""

from __future__ import annotations

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain import FindingKind, VibrationSource
from vibesensor.shared.constants import SPEED_COVERAGE_MIN_PCT
from vibesensor.shared.types.json_types import JsonObject

from ._types import Sample
from .helpers import _effective_engine_rpm

__all__ = [
    "_reference_missing_finding",
    "build_reference_findings",
    "engine_reference_coverage_pct",
    "has_engine_reference",
]


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: VibrationSource,
    kind: FindingKind = FindingKind.REFERENCE,
) -> DomainFinding:
    return DomainFinding(
        finding_id=finding_id,
        suspected_source=suspected_source,
        confidence=None,
        kind=kind,
    )


def build_reference_findings(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    speed_sufficient: bool,
    tire_circumference_m: float | None,
    raw_sample_rate_hz: float | None,
) -> tuple[list[DomainFinding], bool]:
    """Build reference-missing findings and return engine reference sufficiency."""
    findings: list[DomainFinding] = []
    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source=VibrationSource.UNKNOWN,
            ),
        )

    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source=VibrationSource.WHEEL_TIRE,
            ),
        )

    engine_ref_sufficient = has_engine_reference(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    if not engine_ref_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source=VibrationSource.ENGINE,
            ),
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source=VibrationSource.UNKNOWN,
            ),
        )
    return findings, engine_ref_sufficient


def engine_reference_coverage_pct(
    samples: list[Sample],
    *,
    metadata: JsonObject,
    tire_circumference_m: float | None,
) -> float:
    """Compute engine reference coverage percentage from samples and metadata."""
    engine_ref_count = sum(
        1
        for sample in samples
        if (_effective_engine_rpm(sample, metadata, tire_circumference_m)[0] or 0) > 0
    )
    return (engine_ref_count / len(samples) * 100.0) if samples else 0.0


def has_engine_reference(
    samples: list[Sample],
    *,
    metadata: JsonObject,
    tire_circumference_m: float | None,
) -> bool:
    """Return whether the engine reference coverage is sufficient."""
    return bool(
        engine_reference_coverage_pct(
            samples,
            metadata=metadata,
            tire_circumference_m=tire_circumference_m,
        )
        >= SPEED_COVERAGE_MIN_PCT
    )
