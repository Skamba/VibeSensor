"""Row-to-record projection functions for history DB queries."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import cast

from vibesensor.common.json_types import is_json_object
from vibesensor.common.json_utils import safe_json_loads
from vibesensor.domain.run_status import RunStatus
from vibesensor.history.raw_capture_store import (
    HistoryRawCaptureStore,
)
from vibesensor.history.records import (
    ArtifactAvailabilityState,
    HistoryArtifactAvailability,
    HistoryRunListEntry,
    StoredHistoryRun,
)
from vibesensor.history.run_lifecycle import (
    RunArtifactLifecycle,
    derive_run_artifact_lifecycle,
)
from vibesensor.recording.raw_capture import RawCaptureManifest
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.recording.run_schema import RunMetadata, RunRawCaptureFinalize
from vibesensor.summary.persisted_analysis import PersistedAnalysis
from vibesensor.summary.persisted_codec import (
    persisted_analysis_from_storage_json_object,
)

LOGGER = logging.getLogger(__name__)


def _sqlite_int_or_zero(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        return int(value)
    raise TypeError(f"Expected SQLite integer-compatible value, got {type(value).__name__}")


def _artifact_availability_state(
    state: str,
) -> ArtifactAvailabilityState:
    return cast(
        ArtifactAvailabilityState,
        "available" if state == "ready" else state,
    )


def _artifact_availability(
    *,
    lifecycle: RunArtifactLifecycle,
) -> HistoryArtifactAvailability:
    return HistoryArtifactAvailability(
        raw_capture=_artifact_availability_state(lifecycle.raw_capture),
    )


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


def coerce_run_metadata(
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
            return _fallback_run_metadata(
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


def coerce_raw_capture_manifest(
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
    try:
        return RawCaptureManifest.from_mapping(parsed)
    except ValueError:
        LOGGER.warning(
            "%s: run %s raw_capture_manifest_json is corrupt or unsupported",
            source,
            run_id,
            exc_info=True,
        )
        return None


def _coerce_analysis(
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
    *,
    raw_capture_store: HistoryRawCaptureStore,
    run_id: str,
    status: RunStatus,
    has_raw_capture_manifest: bool,
    raw_capture_finalize: RunRawCaptureFinalize | None,
    has_analysis: bool,
    analysis_corrupt: bool,
) -> RunArtifactLifecycle:
    return derive_run_artifact_lifecycle(
        status=status,
        has_raw_capture_manifest=has_raw_capture_manifest,
        raw_capture_artifacts_present=(
            has_raw_capture_manifest and raw_capture_store.has_run_artifacts(run_id)
        ),
        raw_capture_finalize=raw_capture_finalize,
        has_analysis=has_analysis,
        analysis_corrupt=analysis_corrupt,
    )


def project_run_list_entry(
    row: Sequence[object],
    *,
    raw_capture_store: HistoryRawCaptureStore,
) -> HistoryRunListEntry:
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
    ) = row
    normalized_run_id = str(run_id)
    normalized_start = str(start)
    normalized_end = str(end) if end is not None else None
    metadata = coerce_run_metadata(
        run_id=normalized_run_id,
        start_time_utc="",
        end_time_utc=None,
        metadata_json=str(metadata_json) if metadata_json is not None else None,
        source="list_runs",
        allow_fallback=False,
    )
    raw_capture_finalize = None if metadata is None else metadata.raw_capture_finalize
    status = RunStatus(str(status_raw))
    analysis, analysis_corrupt = _coerce_analysis(
        run_id=normalized_run_id,
        analysis_json=str(analysis_json) if analysis_json is not None else None,
        source="list_runs",
    )
    lifecycle = _run_lifecycle(
        raw_capture_store=raw_capture_store,
        run_id=normalized_run_id,
        status=status,
        has_raw_capture_manifest=raw_capture_manifest_json is not None,
        raw_capture_finalize=raw_capture_finalize,
        has_analysis=analysis is not None,
        analysis_corrupt=analysis_corrupt,
    )
    raw_capture_manifest = coerce_raw_capture_manifest(
        run_id=normalized_run_id,
        manifest_json=str(raw_capture_manifest_json)
        if raw_capture_manifest_json is not None
        else None,
        source="list_runs",
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
        artifact_availability=_artifact_availability(lifecycle=lifecycle),
        raw_capture_finalize=raw_capture_finalize,
        raw_sample_count=(
            raw_capture_manifest.total_samples if raw_capture_manifest is not None else None
        ),
        start_time_unverified=metadata is not None and metadata.start_time_unverified,
        interrupted=metadata is not None and metadata.interrupted,
    )


def project_stored_run(
    row: Sequence[object],
    *,
    raw_capture_store: HistoryRawCaptureStore,
) -> StoredHistoryRun:
    (
        rid,
        case_id,
        status_raw,
        start,
        end,
        meta_json,
        raw_capture_manifest_json,
        analysis_json,
        error,
        created,
        sample_count,
        analysis_started,
        analysis_completed,
    ) = row
    normalized_run_id = str(rid)
    status = RunStatus(str(status_raw))
    metadata = coerce_run_metadata(
        run_id=normalized_run_id,
        start_time_utc=str(start),
        end_time_utc=str(end) if end is not None else None,
        metadata_json=str(meta_json) if meta_json is not None else None,
        source="get_run",
        allow_fallback=True,
    )
    assert metadata is not None
    has_raw_capture_manifest = raw_capture_manifest_json is not None
    raw_capture_manifest = coerce_raw_capture_manifest(
        run_id=normalized_run_id,
        manifest_json=str(raw_capture_manifest_json)
        if raw_capture_manifest_json is not None
        else None,
        source="get_run",
    )
    analysis, analysis_corrupt = _coerce_analysis(
        run_id=normalized_run_id,
        analysis_json=str(analysis_json) if analysis_json is not None else None,
        source="get_run",
    )
    lifecycle = _run_lifecycle(
        raw_capture_store=raw_capture_store,
        run_id=normalized_run_id,
        status=status,
        has_raw_capture_manifest=has_raw_capture_manifest,
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
        lifecycle=lifecycle,
        artifact_availability=_artifact_availability(lifecycle=lifecycle),
        raw_capture_finalize=metadata.raw_capture_finalize,
        analysis_corrupt=analysis_corrupt,
        error_message=str(error) if error else None,
        created_at=str(created),
        sample_count=_sqlite_int_or_zero(sample_count),
        analysis_started_at=str(analysis_started) if analysis_started else None,
        analysis_completed_at=str(analysis_completed) if analysis_completed else None,
    )
