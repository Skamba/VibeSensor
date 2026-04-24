"""Boundary codecs for persisted run-suitability checklist payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from vibesensor.domain.run_suitability import RunSuitability, SuitabilityCheck
from vibesensor.shared.json_utils import payload_value_from_json
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.json_types import JsonValue


def _check_details_from_payload(payload: Mapping[str, object]) -> tuple[tuple[str, int], ...]:
    explanation = payload.get("explanation")
    if not isinstance(explanation, Mapping):
        return ()
    details: list[tuple[str, int]] = []
    for key, value in explanation.items():
        if key == "_i18n_key":
            continue
        if isinstance(value, bool):
            details.append((str(key), int(value)))
            continue
        if isinstance(value, int):
            details.append((str(key), value))
            continue
        if isinstance(value, float) and value.is_integer():
            details.append((str(key), int(value)))
            continue
        if isinstance(value, str):
            try:
                details.append((str(key), int(value)))
            except ValueError:
                continue
    return tuple(details)


def run_suitability_from_payload(checks: Sequence[Mapping[str, object]]) -> RunSuitability:
    """Decode persisted checklist payloads into the domain RunSuitability shape."""
    domain_checks = tuple(
        SuitabilityCheck(
            check_key=str(c.get("check_key", "")),
            state=str(c.get("state", "pass")),
            details=_check_details_from_payload(c),
        )
        for c in checks
        if isinstance(c, Mapping)
    )
    return RunSuitability(checks=domain_checks)


def _payload_for_check(check: SuitabilityCheck) -> RunSuitabilityCheck:
    return {
        "check_key": check.check_key,
        "state": check.state,
        "explanation": payload_value_from_json(cast(JsonValue, check.explanation_i18n_ref())),
    }


def run_suitability_payload(
    suitability: RunSuitability | None,
) -> list[RunSuitabilityCheck]:
    """Project a domain RunSuitability into the persisted checklist payload shape."""
    if suitability is None:
        return []
    return [_payload_for_check(check) for check in suitability.checks]
