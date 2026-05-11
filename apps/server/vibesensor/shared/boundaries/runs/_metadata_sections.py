"""Focused run metadata boundary sections."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from vibesensor.domain import Symptom
from vibesensor.shared.boundaries.codecs.scalars import text_or_none
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import (
    RawCaptureFinalizeStatus,
    RunFinalizationStageResult,
    RunFinalizationStageStatus,
    RunRawCaptureFinalize,
    RunSensorMetadata,
)

from ._metadata_codecs import (
    PayloadDecoder,
    PayloadFieldSpec,
    decoded_values,
    finalization_stage_status_decoder,
    float_decoder,
    include_if_nonempty_text,
    include_if_not_none,
    int_decoder,
    json_object_decoder,
    optional_text_decoder,
    project_payload_fields,
    raw_capture_finalize_status_decoder,
    required_text_decoder,
    tuple_text_decoder,
)


@dataclass(frozen=True, slots=True)
class _ReferenceContextState:
    wheel_circumference_m: float | None


@dataclass(frozen=True, slots=True)
class _SymptomState:
    description: str
    onset: str
    context: str


@dataclass(frozen=True, slots=True)
class _RunSensorSnapshotState:
    sensor_id: str
    display_name: str
    location_code: str
    mount_orientation: str | None
    sample_rate_hz: int | None
    firmware_version: str | None


@dataclass(frozen=True, slots=True)
class _RunRawCaptureFinalizeState:
    status: RawCaptureFinalizeStatus | None
    queue_depth: int | None
    error_summary: str | None


@dataclass(frozen=True, slots=True)
class _RunFinalizationStageResultState:
    stage_name: str
    status: RunFinalizationStageStatus | None
    duration_ms: int
    artifacts_created: tuple[str, ...]
    warnings: tuple[str, ...]
    diagnostic_context: JsonObject


_REFERENCE_CONTEXT_FIELD_SPECS: tuple[PayloadFieldSpec, ...] = (
    PayloadFieldSpec(
        "tire_circumference_m",
        "wheel_circumference_m",
        float_decoder("tire_circumference_m"),
        include=include_if_not_none,
    ),
)
_SYMPTOM_FIELD_SPECS: tuple[PayloadFieldSpec, ...] = (
    PayloadFieldSpec("description", "description", required_text_decoder("description")),
    PayloadFieldSpec(
        "onset",
        "onset",
        required_text_decoder("onset"),
        include=include_if_nonempty_text,
    ),
    PayloadFieldSpec(
        "context",
        "context",
        required_text_decoder("context"),
        include=include_if_nonempty_text,
    ),
)
_RUN_SENSOR_SNAPSHOT_ENCODE_FIELD_SPECS: tuple[PayloadFieldSpec, ...] = (
    PayloadFieldSpec("sensor_id", "sensor_id", required_text_decoder("sensor_id")),
    PayloadFieldSpec("display_name", "display_name", required_text_decoder("display_name")),
    PayloadFieldSpec("location_code", "location_code", required_text_decoder("location_code")),
    PayloadFieldSpec(
        "mount_orientation",
        "mount_orientation",
        optional_text_decoder("mount_orientation"),
        include=include_if_not_none,
    ),
    PayloadFieldSpec(
        "sample_rate_hz",
        "sample_rate_hz",
        int_decoder("sample_rate_hz"),
        include=include_if_not_none,
    ),
    PayloadFieldSpec(
        "firmware_version",
        "firmware_version",
        optional_text_decoder("firmware_version"),
        include=include_if_not_none,
    ),
)
_RUN_RAW_CAPTURE_FINALIZE_FIELD_SPECS: tuple[PayloadFieldSpec, ...] = (
    PayloadFieldSpec(
        "status",
        "status",
        raw_capture_finalize_status_decoder("status"),
    ),
    PayloadFieldSpec(
        "queue_depth",
        "queue_depth",
        int_decoder("queue_depth"),
        include=include_if_not_none,
    ),
    PayloadFieldSpec(
        "error_summary",
        "error_summary",
        optional_text_decoder("error_summary"),
        include=include_if_not_none,
    ),
)
_RUN_FINALIZATION_STAGE_FIELD_SPECS: tuple[PayloadFieldSpec, ...] = (
    PayloadFieldSpec("stage_name", "stage_name", required_text_decoder("stage_name")),
    PayloadFieldSpec("status", "status", finalization_stage_status_decoder("status")),
    PayloadFieldSpec("duration_ms", "duration_ms", int_decoder("duration_ms")),
    PayloadFieldSpec(
        "artifacts_created",
        "artifacts_created",
        tuple_text_decoder("artifacts_created"),
        include=lambda value: bool(value),
    ),
    PayloadFieldSpec(
        "warnings",
        "warnings",
        tuple_text_decoder("warnings"),
        include=lambda value: bool(value),
    ),
    PayloadFieldSpec(
        "diagnostic_context",
        "diagnostic_context",
        json_object_decoder("diagnostic_context"),
        include=lambda value: bool(value),
    ),
)
_REFERENCE_CONTEXT_STATE_FACTORY: Callable[..., _ReferenceContextState] = _ReferenceContextState
_SYMPTOM_STATE_FACTORY: Callable[..., _SymptomState] = _SymptomState
_RUN_SENSOR_SNAPSHOT_STATE_FACTORY: Callable[..., _RunSensorSnapshotState] = _RunSensorSnapshotState
_RUN_RAW_CAPTURE_FINALIZE_STATE_FACTORY: Callable[..., _RunRawCaptureFinalizeState] = (
    _RunRawCaptureFinalizeState
)
_RUN_FINALIZATION_STAGE_RESULT_STATE_FACTORY: Callable[..., _RunFinalizationStageResultState] = (
    _RunFinalizationStageResultState
)


def reference_tire_circumference(payload: object) -> float | None:
    if (state := _reference_context_from_payload(payload)) is None:
        return None
    return state.wheel_circumference_m


def reference_context_to_json_object(wheel_circumference_m: float | None) -> JsonObject | None:
    if wheel_circumference_m is None:
        return None
    return project_payload_fields(
        _ReferenceContextState(wheel_circumference_m=wheel_circumference_m),
        _REFERENCE_CONTEXT_FIELD_SPECS,
    )


def symptom_from_payload(payload: object) -> Symptom | None:
    state = _symptom_state_from_mapping(payload)
    if state is None:
        return None
    return Symptom(
        description=state.description,
        onset=state.onset,
        context=state.context,
    )


def symptom_to_json_object(symptom: Symptom | None) -> JsonObject | None:
    if symptom is None or symptom.is_unspecified:
        return None
    return project_payload_fields(symptom, _SYMPTOM_FIELD_SPECS)


def run_sensor_snapshots_from_payload(payload: object) -> tuple[RunSensorMetadata, ...]:
    records: list[RunSensorMetadata] = []
    if isinstance(payload, Mapping):
        iterable: list[tuple[object, object]] = list(payload.items())
        for sensor_id, entry in iterable:
            if not isinstance(entry, Mapping):
                continue
            snapshot = _run_sensor_snapshot_from_mapping(entry, fallback_sensor_id=sensor_id)
            if snapshot is not None:
                records.append(snapshot)
    elif isinstance(payload, list):
        for entry in payload:
            snapshot = _run_sensor_snapshot_from_mapping(entry)
            if snapshot is not None:
                records.append(snapshot)
    records.sort(key=lambda snapshot: snapshot.sensor_id)
    return tuple(records)


def run_sensor_snapshot_to_json_object(snapshot: RunSensorMetadata) -> JsonObject:
    return project_payload_fields(snapshot, _RUN_SENSOR_SNAPSHOT_ENCODE_FIELD_SPECS)


def run_raw_capture_finalize_from_payload(payload: object) -> RunRawCaptureFinalize | None:
    state = _run_raw_capture_finalize_state_from_mapping(payload)
    if state is None or state.status is None:
        return None
    return RunRawCaptureFinalize(
        status=state.status,
        queue_depth=state.queue_depth,
        error_summary=state.error_summary,
    )


def run_raw_capture_finalize_to_json_object(
    finalize: RunRawCaptureFinalize,
) -> JsonObject:
    return project_payload_fields(finalize, _RUN_RAW_CAPTURE_FINALIZE_FIELD_SPECS)


def run_finalization_stages_from_payload(
    payload: object,
) -> tuple[RunFinalizationStageResult, ...]:
    if not isinstance(payload, list):
        return ()
    stages: list[RunFinalizationStageResult] = []
    for entry in payload:
        stage = _run_finalization_stage_from_payload(entry)
        if stage is not None:
            stages.append(stage)
    return tuple(stages)


def run_finalization_stage_to_json_object(
    stage: RunFinalizationStageResult,
) -> JsonObject:
    return stage.to_json_object()


def _reference_context_from_payload(payload: object) -> _ReferenceContextState | None:
    if not isinstance(payload, Mapping):
        return None
    return _REFERENCE_CONTEXT_STATE_FACTORY(
        **decoded_values(payload, _REFERENCE_CONTEXT_FIELD_SPECS)
    )


def _symptom_state_from_mapping(payload: object) -> _SymptomState | None:
    if not isinstance(payload, Mapping):
        return None
    state = _SYMPTOM_STATE_FACTORY(**decoded_values(payload, _SYMPTOM_FIELD_SPECS))
    if not state.description:
        return None
    return state


def _sensor_id_decoder(*, fallback_sensor_id: object = None) -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return (
            text_or_none(payload.get("sensor_id"))
            or text_or_none(payload.get("client_id"))
            or text_or_none(fallback_sensor_id)
            or ""
        )

    return decode


def _display_name_decoder() -> PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return (
            text_or_none(payload.get("display_name"))
            or text_or_none(payload.get("client_name"))
            or ""
        )

    return decode


def _run_sensor_snapshot_decode_field_specs(
    *,
    fallback_sensor_id: object = None,
) -> tuple[PayloadFieldSpec, ...]:
    return (
        PayloadFieldSpec(
            "sensor_id",
            "sensor_id",
            _sensor_id_decoder(fallback_sensor_id=fallback_sensor_id),
        ),
        PayloadFieldSpec("display_name", "display_name", _display_name_decoder()),
        PayloadFieldSpec("location_code", "location_code", required_text_decoder("location_code")),
        PayloadFieldSpec(
            "mount_orientation",
            "mount_orientation",
            optional_text_decoder("mount_orientation"),
        ),
        PayloadFieldSpec("sample_rate_hz", "sample_rate_hz", int_decoder("sample_rate_hz")),
        PayloadFieldSpec(
            "firmware_version",
            "firmware_version",
            optional_text_decoder("firmware_version"),
        ),
    )


def _run_sensor_snapshot_from_mapping(
    payload: object,
    *,
    fallback_sensor_id: object = None,
) -> RunSensorMetadata | None:
    state = _run_sensor_snapshot_state_from_mapping(
        payload,
        fallback_sensor_id=fallback_sensor_id,
    )
    if state is None:
        return None
    return RunSensorMetadata(
        sensor_id=state.sensor_id,
        display_name=state.display_name,
        location_code=state.location_code,
        mount_orientation=state.mount_orientation,
        sample_rate_hz=state.sample_rate_hz,
        firmware_version=state.firmware_version,
    )


def _run_sensor_snapshot_state_from_mapping(
    payload: object,
    *,
    fallback_sensor_id: object = None,
) -> _RunSensorSnapshotState | None:
    if not isinstance(payload, Mapping):
        return None
    state = _RUN_SENSOR_SNAPSHOT_STATE_FACTORY(
        **decoded_values(
            payload,
            _run_sensor_snapshot_decode_field_specs(
                fallback_sensor_id=fallback_sensor_id,
            ),
        )
    )
    if not state.sensor_id:
        return None
    return state


def _run_raw_capture_finalize_state_from_mapping(
    payload: object,
) -> _RunRawCaptureFinalizeState | None:
    if not isinstance(payload, Mapping):
        return None
    state = _RUN_RAW_CAPTURE_FINALIZE_STATE_FACTORY(
        **decoded_values(payload, _RUN_RAW_CAPTURE_FINALIZE_FIELD_SPECS),
    )
    if state.status is None:
        return None
    return state


def _run_finalization_stage_from_payload(
    payload: object,
) -> RunFinalizationStageResult | None:
    if not isinstance(payload, Mapping):
        return None
    state = _RUN_FINALIZATION_STAGE_RESULT_STATE_FACTORY(
        **decoded_values(payload, _RUN_FINALIZATION_STAGE_FIELD_SPECS)
    )
    if not state.stage_name or state.status is None:
        return None
    duration_ms = state.duration_ms if isinstance(state.duration_ms, int) else 0
    return RunFinalizationStageResult(
        stage_name=state.stage_name,
        status=state.status,
        duration_ms=max(0, duration_ms),
        artifacts_created=state.artifacts_created,
        warnings=state.warnings,
        diagnostic_context=state.diagnostic_context,
    )
