"""Row-to-domain projection helpers for HistoryDB queries."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol, cast

from vibesensor.adapters.persistence.history_db._raw_capture_store import (
    HistoryRawCaptureStore,
)
from vibesensor.adapters.persistence.history_db._whole_run_artifact_store import (
    HistoryWholeRunArtifactStore,
)
from vibesensor.domain.run_status import RunStatus
from vibesensor.shared.boundaries.analysis_payloads import (
    persisted_analysis_from_storage_json_object,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.json_utils import safe_json_loads
from vibesensor.shared.types.history_records import (
    ArtifactAvailabilityState,
    HistoryArtifactAvailability,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.raw_capture import RawCaptureManifest
from vibesensor.shared.types.run_lifecycle import (
    RunArtifactLifecycle,
    derive_run_artifact_lifecycle,
)
from vibesensor.shared.types.run_schema import RunMetadata, RunRawCaptureFinalize
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest

LOGGER = logging.getLogger(__name__)


def _sqlite_int_or_zero(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        return int(value)
    raise TypeError(f"Expected SQLite integer-compatible value, got {type(value).__name__}")


class _HistoryDBRunProjectionMixin(Protocol):
    _raw_capture_store: HistoryRawCaptureStore
    _whole_run_artifact_store: HistoryWholeRunArtifactStore

    @staticmethod
    def _artifact_availability_state(
        state: str,
    ) -> ArtifactAvailabilityState:
        return cast(
            ArtifactAvailabilityState,
            "available" if state == "ready" else state,
        )

    def _artifact_availability(
        self,
        *,
        lifecycle: RunArtifactLifecycle,
    ) -> HistoryArtifactAvailability:
        return HistoryArtifactAvailability(
            raw_capture=self._artifact_availability_state(lifecycle.raw_capture),
            whole_run_artifacts=self._artifact_availability_state(lifecycle.whole_run_artifacts),
        )

    @staticmethod
    def _fallback_run_metadata(
        *,
        run_id: str,
        start_time_utc: str,
        end_time_utc: str | None,
    ) -> RunMetadata:
        return run_metadata_from_mapping(
            {
                "run_id": run_id,
                "start_time_utc": start_time_utc,
                "end_time_utc": end_time_utc,
                "sensor_model": "unknown",
            }
        )

    def _coerce_run_metadata(
        self,
        *,
        run_id: str,
        start_time_utc: str,
        end_time_utc: str | None,
        metadata_json: str | None,
        source: str,
        allow_fallback: bool,
    ) -> RunMetadata | None:
        parsed = safe_json_loads(metadata_json, context=f"run {run_id} metadata")
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "%s: run %s metadata_json parsed to %s, expected dict; %s",
                    source,
                    run_id,
                    type(parsed).__name__,
                    "using fallback metadata object" if allow_fallback else "returning None",
                )
            if allow_fallback:
                return self._fallback_run_metadata(
                    run_id=run_id,
                    start_time_utc=start_time_utc,
                    end_time_utc=end_time_utc,
                )
            return None
        if "start_time_utc" not in parsed:
            parsed["start_time_utc"] = start_time_utc
        if end_time_utc and "end_time_utc" not in parsed:
            parsed["end_time_utc"] = end_time_utc
        return run_metadata_from_mapping(parsed)

    def _coerce_raw_capture_manifest(
        self,
        *,
        run_id: str,
        manifest_json: str | None,
        source: str,
    ) -> RawCaptureManifest | None:
        parsed = safe_json_loads(manifest_json, context=f"run {run_id} raw_capture_manifest")
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "%s: run %s raw_capture_manifest_json parsed to %s, expected dict",
                    source,
                    run_id,
                    type(parsed).__name__,
                )
            return None
        return RawCaptureManifest.from_mapping(parsed)

    def _coerce_whole_run_artifact_manifest(
        self,
        *,
        run_id: str,
        manifest_json: str | None,
        source: str,
    ) -> WholeRunArtifactManifest | None:
        parsed = safe_json_loads(
            manifest_json,
            context=f"run {run_id} whole_run_artifact_manifest",
        )
        if not is_json_object(parsed):
            if parsed is not None:
                LOGGER.warning(
                    "%s: run %s whole_run_artifact_manifest_json parsed to %s, expected dict",
                    source,
                    run_id,
                    type(parsed).__name__,
                )
            return None
        try:
            return WholeRunArtifactManifest.from_mapping(parsed)
        except (TypeError, ValueError):
            LOGGER.warning(
                "%s: run %s whole_run_artifact_manifest_json is corrupt or unsupported",
                source,
                run_id,
                exc_info=True,
            )
            return None

    def _coerce_raw_capture_finalize(
        self,
        *,
        run_id: str,
        metadata_json: str | None,
        source: str,
    ) -> RunRawCaptureFinalize | None:
        metadata = self._coerce_run_metadata(
            run_id=run_id,
            start_time_utc="",
            end_time_utc=None,
            metadata_json=metadata_json,
            source=source,
            allow_fallback=False,
        )
        return None if metadata is None else metadata.raw_capture_finalize

    def _coerce_analysis(
        self,
        *,
        run_id: str,
        analysis_json: str | None,
        source: str,
    ) -> tuple[PersistedAnalysis | None, bool]:
        if not analysis_json:
            return None, False
        parsed_analysis = safe_json_loads(analysis_json, context=f"run {run_id} analysis")
        if not is_json_object(parsed_analysis):
            LOGGER.warning(
                "%s: run %s analysis_json parsed to %s, expected dict",
                source,
                run_id,
                type(parsed_analysis).__name__,
            )
            return None, True
        try:
            return persisted_analysis_from_storage_json_object(parsed_analysis), False
        except ValueError:
            LOGGER.warning(
                "%s: analysis for run %s used an unsupported storage schema version",
                source,
                run_id,
                exc_info=True,
            )
            return None, True

    def _run_lifecycle(
        self,
        *,
        run_id: str,
        status: RunStatus,
        has_raw_capture_manifest: bool,
        whole_run_artifact_manifest: WholeRunArtifactManifest | None,
        raw_capture_finalize: RunRawCaptureFinalize | None,
        has_analysis: bool,
        analysis_corrupt: bool,
    ) -> RunArtifactLifecycle:
        return derive_run_artifact_lifecycle(
            status=status,
            has_raw_capture_manifest=has_raw_capture_manifest,
            raw_capture_artifacts_present=(
                has_raw_capture_manifest and self._raw_capture_store.has_run_artifacts(run_id)
            ),
            has_whole_run_artifact_manifest=whole_run_artifact_manifest is not None,
            whole_run_artifacts_present=(
                whole_run_artifact_manifest is not None
                and self._whole_run_artifact_store.has_manifest_artifacts(
                    whole_run_artifact_manifest
                )
            ),
            raw_capture_finalize=raw_capture_finalize,
            has_analysis=has_analysis,
            analysis_corrupt=analysis_corrupt,
        )

    def _project_run_list_entry(self, row: Sequence[object]) -> HistoryRunListEntry:
        (
            run_id,
            status_raw,
            start,
            end,
            created,
            error,
            sample_count,
            car_name,
            metadata_json,
            analysis_json,
            raw_capture_manifest_json,
            whole_run_artifact_manifest_json,
        ) = row
        normalized_run_id = str(run_id)
        normalized_start = str(start)
        normalized_end = str(end) if end is not None else None
        raw_capture_finalize = self._coerce_raw_capture_finalize(
            run_id=normalized_run_id,
            metadata_json=str(metadata_json) if metadata_json is not None else None,
            source="list_runs",
        )
        status = RunStatus(str(status_raw))
        analysis, analysis_corrupt = self._coerce_analysis(
            run_id=normalized_run_id,
            analysis_json=str(analysis_json) if analysis_json is not None else None,
            source="list_runs",
        )
        whole_run_artifact_manifest = self._coerce_whole_run_artifact_manifest(
            run_id=normalized_run_id,
            manifest_json=str(whole_run_artifact_manifest_json)
            if whole_run_artifact_manifest_json is not None
            else None,
            source="list_runs",
        )
        lifecycle = self._run_lifecycle(
            run_id=normalized_run_id,
            status=status,
            has_raw_capture_manifest=raw_capture_manifest_json is not None,
            whole_run_artifact_manifest=whole_run_artifact_manifest,
            raw_capture_finalize=raw_capture_finalize,
            has_analysis=analysis is not None,
            analysis_corrupt=analysis_corrupt,
        )
        return HistoryRunListEntry(
            run_id=normalized_run_id,
            status=status,
            start_time_utc=normalized_start,
            end_time_utc=normalized_end,
            created_at=str(created),
            sample_count=_sqlite_int_or_zero(sample_count),
            car_name=str(car_name) if car_name else None,
            error_message=str(error) if error else None,
            lifecycle=lifecycle,
            artifact_availability=self._artifact_availability(lifecycle=lifecycle),
            raw_capture_finalize=raw_capture_finalize,
        )

    def _project_stored_run(self, row: Sequence[object]) -> StoredHistoryRun:
        (
            rid,
            case_id,
            status_raw,
            start,
            end,
            meta_json,
            raw_capture_manifest_json,
            whole_run_artifact_manifest_json,
            analysis_json,
            error,
            created,
            sample_count,
            analysis_started,
            analysis_completed,
        ) = row
        normalized_run_id = str(rid)
        status = RunStatus(str(status_raw))
        metadata = self._coerce_run_metadata(
            run_id=normalized_run_id,
            start_time_utc=str(start),
            end_time_utc=str(end) if end is not None else None,
            metadata_json=str(meta_json) if meta_json is not None else None,
            source="get_run",
            allow_fallback=True,
        )
        assert metadata is not None
        has_raw_capture_manifest = raw_capture_manifest_json is not None
        raw_capture_manifest = self._coerce_raw_capture_manifest(
            run_id=normalized_run_id,
            manifest_json=str(raw_capture_manifest_json)
            if raw_capture_manifest_json is not None
            else None,
            source="get_run",
        )
        whole_run_artifact_manifest = self._coerce_whole_run_artifact_manifest(
            run_id=normalized_run_id,
            manifest_json=str(whole_run_artifact_manifest_json)
            if whole_run_artifact_manifest_json is not None
            else None,
            source="get_run",
        )
        analysis, analysis_corrupt = self._coerce_analysis(
            run_id=normalized_run_id,
            analysis_json=str(analysis_json) if analysis_json is not None else None,
            source="get_run",
        )
        lifecycle = self._run_lifecycle(
            run_id=normalized_run_id,
            status=status,
            has_raw_capture_manifest=has_raw_capture_manifest,
            whole_run_artifact_manifest=whole_run_artifact_manifest,
            raw_capture_finalize=metadata.raw_capture_finalize,
            has_analysis=analysis is not None,
            analysis_corrupt=analysis_corrupt,
        )
        return StoredHistoryRun(
            run_id=normalized_run_id,
            case_id=str(case_id) if case_id is not None else None,
            status=status,
            start_time_utc=str(start),
            end_time_utc=str(end) if end is not None else None,
            metadata=metadata,
            analysis=analysis,
            raw_capture_manifest=raw_capture_manifest,
            whole_run_artifact_manifest=whole_run_artifact_manifest,
            lifecycle=lifecycle,
            artifact_availability=self._artifact_availability(lifecycle=lifecycle),
            raw_capture_finalize=metadata.raw_capture_finalize,
            analysis_corrupt=analysis_corrupt,
            error_message=str(error) if error else None,
            created_at=str(created),
            sample_count=_sqlite_int_or_zero(sample_count),
            analysis_started_at=str(analysis_started) if analysis_started else None,
            analysis_completed_at=str(analysis_completed) if analysis_completed else None,
        )
