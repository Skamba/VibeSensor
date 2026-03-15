"""Internal helpers shared across boundary modules."""

from __future__ import annotations

from collections.abc import Mapping


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payloads_by_id(items: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(items, list):
        return {}
    payloads: dict[str, Mapping[str, object]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        finding_id = str(item.get("finding_id") or "").strip()
        if finding_id and finding_id not in payloads:
            payloads[finding_id] = item
    return payloads


def _has_structured_step_content(steps: object) -> bool:
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        for key in ("what", "why", "confirm", "falsify"):
            value = step.get(key)
            if isinstance(value, (Mapping, list)):
                return True
    return False
