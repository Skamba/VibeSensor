"""Boundary decoders and projectors for RunSuitability payload shapes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..domain.run_suitability import RunSuitability, SuitabilityCheck

__all__ = ["run_suitability_from_payload", "run_suitability_payload"]


def _i18n_ref(key: str, **kwargs: object) -> dict[str, object]:
    return {"_i18n_key": key, **kwargs}


def run_suitability_from_payload(checks: Sequence[Mapping[str, object]]) -> RunSuitability:
    """Decode persisted checklist payloads into the domain RunSuitability shape."""
    domain_checks = tuple(
        SuitabilityCheck(
            check_key=str(c.get("check_key", c.get("check", ""))),
            state=str(c.get("state", "pass")),
        )
        for c in checks
        if isinstance(c, Mapping)
    )
    return RunSuitability(checks=domain_checks)


def _fallback_check_by_key(
    fallback: Sequence[Mapping[str, object]] | None,
) -> dict[str, Mapping[str, object]]:
    if fallback is None:
        return {}
    return {
        str(check.get("check_key") or check.get("check") or ""): check
        for check in fallback
        if isinstance(check, Mapping)
    }


def _payload_for_check(
    check: SuitabilityCheck,
    *,
    fallback: Mapping[str, object] | None,
) -> dict[str, object]:
    details = check.details_dict
    if check.check_key == "SUITABILITY_CHECK_SPEED_VARIATION":
        explanation = (
            _i18n_ref("SUITABILITY_SPEED_VARIATION_PASS")
            if check.state == "pass"
            else _i18n_ref("SUITABILITY_SPEED_VARIATION_WARN")
        )
    elif check.check_key == "SUITABILITY_CHECK_SENSOR_COVERAGE":
        explanation = (
            _i18n_ref("SUITABILITY_SENSOR_COVERAGE_PASS")
            if check.state == "pass"
            else _i18n_ref("SUITABILITY_SENSOR_COVERAGE_WARN")
        )
    elif check.check_key == "SUITABILITY_CHECK_REFERENCE_COMPLETENESS":
        explanation = (
            _i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_PASS")
            if check.state == "pass"
            else _i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_WARN")
        )
    elif check.check_key == "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS":
        sat_count = int(details.get("sat_count", 0))
        explanation = (
            _i18n_ref("SUITABILITY_SATURATION_PASS")
            if check.state == "pass"
            else _i18n_ref("SUITABILITY_SATURATION_WARN", sat_count=sat_count)
        )
    elif check.check_key == "SUITABILITY_CHECK_FRAME_INTEGRITY":
        total_dropped = int(details.get("total_dropped", 0))
        total_overflow = int(details.get("total_overflow", 0))
        explanation = (
            _i18n_ref("SUITABILITY_FRAME_INTEGRITY_PASS")
            if check.state == "pass"
            else _i18n_ref(
                "SUITABILITY_FRAME_INTEGRITY_WARN",
                total_dropped=total_dropped,
                total_overflow=total_overflow,
            )
        )
    elif fallback is not None:
        explanation = fallback.get("explanation", "")
    else:
        explanation = ""

    if (
        check.state != "pass"
        and not details
        and fallback is not None
        and fallback.get("explanation") is not None
    ):
        explanation = fallback.get("explanation", explanation)

    return {
        "check": check.check_key,
        "check_key": check.check_key,
        "state": check.state,
        "explanation": explanation,
    }


def run_suitability_payload(
    suitability: RunSuitability | None,
    *,
    fallback: Sequence[Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Project a domain RunSuitability into the persisted checklist payload shape."""
    if suitability is None:
        return []
    fallback_by_key = _fallback_check_by_key(fallback)
    return [
        _payload_for_check(
            check,
            fallback=fallback_by_key.get(check.check_key),
        )
        for check in suitability.checks
    ]
