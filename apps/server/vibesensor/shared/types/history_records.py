"""Typed persistence-side history record objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.types.backend_types import RunMetadata
from vibesensor.shared.types.json_types import JsonObject

__all__ = [
    "AnalyzingRunHealth",
    "HistoryRunListEntry",
    "StoredHistoryRun",
]


@dataclass(frozen=True, slots=True)
class HistoryRunListEntry:
    """Typed summary row returned by ``RunPersistence.list_runs()``."""

    run_id: str
    status: RunStatus
    start_time_utc: str
    end_time_utc: str | None
    created_at: str
    sample_count: int
    error_message: str | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "run_id": self.run_id,
            "status": self.status.value,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "created_at": self.created_at,
            "sample_count": self.sample_count,
        }
        if self.error_message is not None:
            payload["error_message"] = self.error_message
        return payload


@dataclass(frozen=True, slots=True)
class StoredHistoryRun:
    """Typed full run record returned by ``RunPersistence.get_run()``."""

    run_id: str
    status: RunStatus
    start_time_utc: str
    end_time_utc: str | None
    metadata: RunMetadata
    created_at: str
    sample_count: int
    case_id: str | None = None
    analysis: AnalysisSummary | None = None
    analysis_corrupt: bool = False
    error_message: str | None = None
    analysis_started_at: str | None = None
    analysis_completed_at: str | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "run_id": self.run_id,
            "status": self.status.value,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "metadata": self.metadata.to_dict(),
            "created_at": self.created_at,
            "sample_count": self.sample_count,
        }
        if self.case_id is not None:
            payload["case_id"] = self.case_id
        if self.analysis is not None:
            payload["analysis"] = cast(JsonObject, dict(self.analysis))
        if self.analysis_corrupt:
            payload["analysis_corrupt"] = True
        if self.error_message is not None:
            payload["error_message"] = self.error_message
        if self.analysis_started_at is not None:
            payload["analysis_started_at"] = self.analysis_started_at
        if self.analysis_completed_at is not None:
            payload["analysis_completed_at"] = self.analysis_completed_at
        return payload


@dataclass(frozen=True, slots=True)
class AnalyzingRunHealth:
    """Typed analyzer-health snapshot returned by ``RunPersistence``."""

    analyzing_run_count: int
    analyzing_oldest_age_s: float | None
    analyzing_oldest_started_at: str | None = None

    def to_json_object(self) -> JsonObject:
        payload: JsonObject = {
            "analyzing_run_count": self.analyzing_run_count,
            "analyzing_oldest_age_s": self.analyzing_oldest_age_s,
        }
        if self.analyzing_oldest_started_at is not None:
            payload["analyzing_oldest_started_at"] = self.analyzing_oldest_started_at
        return payload
