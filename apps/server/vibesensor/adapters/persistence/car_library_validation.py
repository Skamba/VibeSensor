"""Public validation facade for bundled vehicle library data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.domain import VehicleConfiguration

from ._car_library_validation_allowlist import (
    filter_allowlisted_issues,
    load_car_library_validation_allowlist,
)
from ._car_library_validation_common import CarLibraryValidationIssue
from ._car_library_validation_exact import (
    validate_vehicle_configuration,
    validate_vehicle_configuration_duplicates,
)
from ._car_library_validation_legacy import validate_legacy_entry

__all__ = [
    "CarLibraryValidationIssue",
    "ensure_valid_car_library_rows",
    "ensure_valid_vehicle_configurations",
    "load_car_library_validation_allowlist",
    "validate_car_library_rows",
    "validate_vehicle_configurations",
]


def ensure_valid_car_library_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> None:
    """Raise ``ValueError`` when legacy car-library rows fail validation."""

    issues = validate_car_library_rows(rows, allowlist=allowlist)
    if issues:
        raise ValueError(_format_issue_summary("car library", issues))


def ensure_valid_vehicle_configurations(
    configs: Sequence[VehicleConfiguration],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> None:
    """Raise ``ValueError`` when exact vehicle configuration rows fail validation."""

    issues = validate_vehicle_configurations(configs, allowlist=allowlist)
    if issues:
        raise ValueError(_format_issue_summary("vehicle configurations", issues))


def validate_car_library_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> tuple[CarLibraryValidationIssue, ...]:
    """Return all validation issues for grouped car-picker rows."""

    issues: list[CarLibraryValidationIssue] = []
    for entry in rows:
        validate_legacy_entry(entry, issues)
    return filter_allowlisted_issues(issues, allowlist)


def validate_vehicle_configurations(
    configs: Sequence[VehicleConfiguration],
    *,
    allowlist: Mapping[tuple[str, str], str] | None = None,
) -> tuple[CarLibraryValidationIssue, ...]:
    """Return all validation issues for exact vehicle configuration rows."""

    issues: list[CarLibraryValidationIssue] = []
    for config in configs:
        validate_vehicle_configuration(config, issues)
    validate_vehicle_configuration_duplicates(configs, issues)
    return filter_allowlisted_issues(issues, allowlist)


def _format_issue_summary(label: str, issues: Sequence[CarLibraryValidationIssue]) -> str:
    lines = [f"Invalid {label}: {len(issues)} issue(s)"]
    lines.extend(f"- [{issue.rule}] {issue.message}" for issue in issues[:10])
    remaining = len(issues) - 10
    if remaining > 0:
        lines.append(f"- ... and {remaining} more")
    return "\n".join(lines)
