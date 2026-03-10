"""Helpers for versioned persisted analysis payloads.

Persisted analysis is stored as an envelope so the on-disk shape can evolve
independently of the public summary dict returned by history APIs.
"""

from __future__ import annotations

import logging

from .history_db._schema import ANALYSIS_SCHEMA_VERSION
from .json_types import JsonObject, is_json_object

LOGGER = logging.getLogger(__name__)


def sanitize_analysis_summary(summary: JsonObject) -> JsonObject:
    normalized = dict(summary)
    normalized.pop("_report_template_data", None)
    return normalized


def wrap_analysis_for_storage(summary: JsonObject) -> JsonObject:
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "summary": sanitize_analysis_summary(summary),
    }


def unwrap_persisted_analysis(raw: JsonObject) -> JsonObject:
    """Extract the analysis summary from a (potentially enveloped) payload."""
    summary = raw.get("summary")
    if is_json_object(summary):
        return sanitize_analysis_summary(summary)
    # Legacy non-enveloped payload — return the raw blob as the summary.
    return sanitize_analysis_summary(raw)


def persisted_analysis_is_current(
    analysis_version: object,
    raw: JsonObject | None,
) -> bool:
    """Check whether a persisted analysis envelope matches the current schema."""
    if raw is None:
        return False
    sv = raw.get("schema_version")
    if not isinstance(sv, int):
        return False
    return sv >= ANALYSIS_SCHEMA_VERSION
