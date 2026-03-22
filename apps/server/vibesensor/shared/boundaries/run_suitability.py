"""Boundary codecs for persisted run-suitability checklist payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from vibesensor.domain.run_suitability import RunSuitability, SuitabilityCheck
from vibesensor.shared.boundaries.analysis_payload import RunSuitabilityCheck
from vibesensor.shared.types.json_types import JsonValue


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


def _payload_for_check(check: SuitabilityCheck) -> RunSuitabilityCheck:
    return {
        "check": check.check_key,
        "check_key": check.check_key,
        "state": check.state,
        "explanation": cast(JsonValue, check.explanation_i18n_ref()),
    }


def run_suitability_payload(
    suitability: RunSuitability | None,
) -> list[RunSuitabilityCheck]:
    """Project a domain RunSuitability into the persisted checklist payload shape."""
    if suitability is None:
        return []
    return [_payload_for_check(check) for check in suitability.checks]
