"""Shared warning contracts and normalization helpers for run-context concerns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.types.json_types import JsonValue, is_json_object

WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE = "reference_context_incomplete"
WARNING_CODE_CAR_SETTINGS_CHANGED = "car_settings_changed"
WARNING_CODE_WHOLE_RUN_CONTEXT_INCOMPLETE = "whole_run_context_incomplete"
WARNING_CODE_WHOLE_RUN_CONTEXT_LEGACY_FALLBACK = "whole_run_context_legacy_fallback"
WARNING_CODE_RAW_REPLAY_COVERAGE_INCOMPLETE = "raw_replay_coverage_incomplete"
WARNING_CODE_RAW_REPLAY_LEGACY_FALLBACK = "raw_replay_legacy_fallback"
WARNING_CODE_RAW_REPLAY_TIMING_FALLBACK = "raw_replay_timing_fallback"
WarningSeverity = Literal["warn", "error"]


@dataclass(frozen=True, slots=True)
class RunContextWarning:
    """App-level warning model shared by diagnostics and history workflows."""

    code: str
    severity: WarningSeverity
    applies_to: str
    title: JsonValue
    detail: JsonValue | None = None


type RunContextWarningsInput = Sequence[RunContextWarning | JsonValue] | None


def build_summary_warnings(
    metadata: Mapping[str, object],
    *,
    reference_complete: bool,
) -> list[RunContextWarning]:
    """Build language-neutral trust warnings stored with the analysis summary."""
    warnings: list[RunContextWarning] = []
    if not reference_complete or bool(metadata.get("incomplete_for_order_analysis")):
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
                severity="warn",
                applies_to="order_analysis",
                title=i18n_ref("RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"),
                detail=i18n_ref("RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"),
            )
        )
    return warnings


def normalize_run_context_warnings(
    warnings: RunContextWarningsInput,
) -> list[RunContextWarning]:
    """Return normalized warning models from stored domain objects or JSON-shaped payloads."""
    if warnings is None:
        return []
    normalized: list[RunContextWarning] = []
    for warning in warnings:
        if isinstance(warning, RunContextWarning):
            normalized.append(warning)
            continue
        if not is_json_object(warning):
            continue
        normalized.append(
            RunContextWarning(
                code=str(warning.get("code") or ""),
                severity=cast(WarningSeverity, str(warning.get("severity") or "warn")),
                applies_to=str(warning.get("applies_to") or "order_analysis"),
                title=warning.get("title"),
                detail=warning.get("detail"),
            )
        )
    return normalized
