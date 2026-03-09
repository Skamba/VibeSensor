"""Helpers for versioned persisted analysis payloads.

Persisted analysis is stored as an envelope so the on-disk shape can evolve
independently of the public summary dict returned by history APIs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .history_db._run_common import ANALYSIS_SCHEMA_VERSION
from .json_types import JsonObject, is_json_object

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PersistedAnalysisRead:
    summary: JsonObject
    schema_version: int | None
    is_enveloped: bool


def _coerce_schema_version(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def sanitize_analysis_summary(summary: JsonObject) -> JsonObject:
    normalized = dict(summary)
    normalized.pop("_report_template_data", None)
    return normalized


def wrap_analysis_for_storage(summary: JsonObject) -> JsonObject:
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "summary": sanitize_analysis_summary(summary),
    }


def unwrap_persisted_analysis(raw: JsonObject) -> PersistedAnalysisRead:
    summary = raw.get("summary")
    if is_json_object(summary):
        sv = _coerce_schema_version(raw.get("schema_version"))
        if sv is not None and sv < ANALYSIS_SCHEMA_VERSION:
            LOGGER.debug(
                "Analysis envelope has outdated schema_version %d (current %d)",
                sv,
                ANALYSIS_SCHEMA_VERSION,
            )
        return PersistedAnalysisRead(
            summary=sanitize_analysis_summary(summary),
            schema_version=sv,
            is_enveloped=True,
        )
    LOGGER.debug(
        "Encountered unversioned (non-enveloped) persisted analysis; "
        "consider re-analyzing this run to upgrade to schema v%d",
        ANALYSIS_SCHEMA_VERSION,
    )
    return PersistedAnalysisRead(
        summary=sanitize_analysis_summary(raw),
        schema_version=None,
        is_enveloped=False,
    )


def persisted_analysis_is_current(
    analysis_version: object,
    raw: JsonObject | None,
) -> bool:
    if raw is None:
        return False
    persisted = unwrap_persisted_analysis(raw)
    try:
        version_current = (
            int(analysis_version) >= ANALYSIS_SCHEMA_VERSION  # type: ignore[call-overload]
            if analysis_version is not None
            else False
        )
    except (TypeError, ValueError):
        return False
    return (
        version_current
        and persisted.is_enveloped
        and (persisted.schema_version == ANALYSIS_SCHEMA_VERSION)
    )
