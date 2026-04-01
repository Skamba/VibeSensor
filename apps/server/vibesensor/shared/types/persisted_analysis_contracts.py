"""Storage-owned wrapper contracts for persisted analysis payloads."""

from __future__ import annotations

from typing import Any, Required

from pydantic import ConfigDict

from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummaryCoreResponse,
    SummaryWarningResponse,
)

__all__ = ["PersistedAnalysisPayload"]


class PersistedAnalysisPayload(AnalysisSummaryCoreResponse):
    """Canonical storage-owned wrapper for persisted analysis payloads."""

    warnings: Required[list[SummaryWarningResponse]]


def _configure_pydantic_schema(typed_dict: Any, config: ConfigDict) -> None:
    typed_dict.__pydantic_config__ = config


_configure_pydantic_schema(PersistedAnalysisPayload, ConfigDict(extra="forbid"))
