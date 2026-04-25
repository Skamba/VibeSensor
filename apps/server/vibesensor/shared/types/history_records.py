"""Typed persistence-side history record objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.run_schema import RunMetadata, RunRawCaptureFinalize
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest

__all__ = [
    "ArtifactAvailabilityState",
    "AnalyzingRunHealth",
    "HistoryArtifactAvailability",
    "HistoryRunListEntry",
    "StoredHistoryRun",
]

type ArtifactAvailabilityState = Literal["not_recorded", "available", "missing", "degraded"]


@dataclass(frozen=True, slots=True)
class HistoryArtifactAvailability:
    """Explicit persisted-artifact availability state projected to history consumers."""

    raw_capture: ArtifactAvailabilityState = "not_recorded"
    whole_run_artifacts: ArtifactAvailabilityState = "not_recorded"

    def to_json_object(self) -> JsonObject:
        return {
            "raw_capture": self.raw_capture,
            "whole_run_artifacts": self.whole_run_artifacts,
        }


@dataclass(frozen=True, slots=True)
class HistoryRunListEntry:
    """Typed summary row returned by ``RunPersistence.list_runs()``."""

    run_id: str
    status: RunStatus
    start_time_utc: str
    end_time_utc: str | None
    created_at: str
    sample_count: int
    car_name: str | None = None
    error_message: str | None = None
    artifact_availability: HistoryArtifactAvailability | None = None
    raw_capture_finalize: RunRawCaptureFinalize | None = None

    def to_json_object(self) -> JsonObject:
        """Serialize the list-entry record into a JSON-safe persistence payload."""
        payload: JsonObject = {
            "run_id": self.run_id,
            "status": self.status.value,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "created_at": self.created_at,
            "sample_count": self.sample_count,
        }
        if self.car_name is not None:
            payload["car_name"] = self.car_name
        if self.error_message is not None:
            payload["error_message"] = self.error_message
        if self.artifact_availability is not None:
            payload["artifact_availability"] = self.artifact_availability.to_json_object()
        if self.raw_capture_finalize is not None:
            payload["raw_capture_finalize"] = self.raw_capture_finalize.to_json_object()
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
    analysis: PersistedAnalysis | None = None
    raw_capture_manifest: RawCaptureManifest | None = None
    whole_run_artifact_manifest: WholeRunArtifactManifest | None = None
    artifact_availability: HistoryArtifactAvailability | None = None
    raw_capture_finalize: RunRawCaptureFinalize | None = None
    analysis_corrupt: bool = False
    error_message: str | None = None
    analysis_started_at: str | None = None
    analysis_completed_at: str | None = None

    def to_json_object(self) -> JsonObject:
        """Serialize the full stored-run record into a JSON-safe payload."""
        payload: JsonObject = {
            "run_id": self.run_id,
            "status": self.status.value,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "metadata": run_metadata_to_json_object(self.metadata),
            "created_at": self.created_at,
            "sample_count": self.sample_count,
        }
        if self.case_id is not None:
            payload["case_id"] = self.case_id
        if self.analysis is not None:
            payload["analysis"] = self.analysis.to_json_object()
        if self.raw_capture_manifest is not None:
            payload["raw_capture_manifest"] = self.raw_capture_manifest.to_json_object()
        if self.whole_run_artifact_manifest is not None:
            payload["whole_run_artifact_manifest"] = (
                self.whole_run_artifact_manifest.to_json_object()
            )
        if self.artifact_availability is not None:
            payload["artifact_availability"] = self.artifact_availability.to_json_object()
        if self.raw_capture_finalize is not None:
            payload["raw_capture_finalize"] = self.raw_capture_finalize.to_json_object()
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
        """Serialize the analyzer-health snapshot into a JSON-safe payload."""
        payload: JsonObject = {
            "analyzing_run_count": self.analyzing_run_count,
            "analyzing_oldest_age_s": self.analyzing_oldest_age_s,
        }
        if self.analyzing_oldest_started_at is not None:
            payload["analyzing_oldest_started_at"] = self.analyzing_oldest_started_at
        return payload
