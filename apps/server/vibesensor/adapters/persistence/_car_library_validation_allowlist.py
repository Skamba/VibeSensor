"""Allowlist loading/filtering for documented vehicle data exceptions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from vibesensor.shared._data_files import resolve_static_data_file

from ._car_library_validation_common import CarLibraryValidationIssue

_ALLOWLIST_FILE = resolve_static_data_file("car_library_validation_allowlist.json")


def load_car_library_validation_allowlist(
    path: Path = _ALLOWLIST_FILE,
) -> dict[tuple[str, str], str]:
    """Load the documented validation allowlist keyed by ``(rule, entity)``."""

    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"Could not load car-library validation allowlist from {path}: {exc}"
        ) from exc

    rows = payload.get("allowances")
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain an 'allowances' list")

    allowlist: dict[tuple[str, str], str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{path} allowance #{index} must be an object")
        rule = row.get("rule")
        entity = row.get("entity")
        reason = row.get("reason")
        if not isinstance(rule, str) or not rule.strip():
            raise ValueError(f"{path} allowance #{index} missing non-empty rule")
        if not isinstance(entity, str) or not entity.strip():
            raise ValueError(f"{path} allowance #{index} missing non-empty entity")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path} allowance #{index} missing non-empty reason")
        key = (rule.strip(), entity.strip())
        if key in allowlist:
            raise ValueError(f"{path} duplicates allowance for rule={rule!r} entity={entity!r}")
        allowlist[key] = reason.strip()
    return allowlist


def filter_allowlisted_issues(
    issues: Sequence[CarLibraryValidationIssue],
    allowlist: Mapping[tuple[str, str], str] | None,
) -> tuple[CarLibraryValidationIssue, ...]:
    allowances = load_car_library_validation_allowlist() if allowlist is None else dict(allowlist)
    return tuple(issue for issue in issues if (issue.rule, issue.entity) not in allowances)
