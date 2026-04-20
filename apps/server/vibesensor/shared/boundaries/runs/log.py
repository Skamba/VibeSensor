"""Shared JSONL run-log boundary decoder used by diagnostics and persistence."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import msgspec

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_json
from vibesensor.shared.boundaries.sensor_frames import (
    SensorFrameDecodeError,
    sensor_frame_from_mapping,
)
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.run_schema import (
    RUN_END_TYPE,
    RUN_METADATA_TYPE,
    RUN_SAMPLE_TYPE,
    RunMetadata,
)
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = [
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RunData",
    "normalize_sample_record",
    "read_jsonl_run",
]

LOGGER = logging.getLogger(__name__)


class _RunEndRecord(msgspec.Struct, kw_only=True, frozen=True):
    """Typed run-end record used for tolerant end-time backfill."""

    record_type: str = RUN_END_TYPE
    end_time_utc: object = None


@dataclass(slots=True)
class RunData:
    """Parsed contents of a JSONL run file: metadata, samples, and source path."""

    metadata: RunMetadata
    samples: list[SensorFrame]
    source_path: Path


def normalize_sample_record(record: dict[str, object]) -> SensorFrame:
    """Normalize a raw sample payload into the canonical typed sample object."""

    return sensor_frame_from_mapping(record, strict=True, source="jsonl sample")


def _run_end_record_from_json(data: str | bytes | bytearray) -> _RunEndRecord:
    """Decode a run-end record through msgspec while tolerating legacy-like shapes."""

    try:
        return msgspec.json.decode(data, type=_RunEndRecord)
    except msgspec.ValidationError:
        payload = msgspec.json.decode(data)
    if not is_json_object(payload):
        raise TypeError("run end JSON must decode to an object")
    return _RunEndRecord(end_time_utc=payload.get("end_time_utc"))


def read_jsonl_run(path: Path) -> RunData:
    """Read a JSONL run file and return parsed metadata and sample records."""
    if not path.exists():
        raise FileNotFoundError(path)

    metadata: RunMetadata | None = None
    end_record: _RunEndRecord | None = None
    samples: list[SensorFrame] = []
    skipped = 0
    _decode = msgspec.json.decode
    _meta_type = RUN_METADATA_TYPE
    _sample_type = RUN_SAMPLE_TYPE
    _end_type = RUN_END_TYPE
    _normalize = normalize_sample_record
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = _decode(text)
            except msgspec.DecodeError as exc:
                LOGGER.warning(
                    "Skipping corrupt JSONL line %d in %s: %s",
                    line_no,
                    path,
                    exc,
                )
                skipped += 1
                continue
            if not is_json_object(payload):
                continue
            record_type = str(payload.get("record_type", ""))
            if record_type == _meta_type and metadata is None:
                metadata = run_metadata_from_json(text)
            elif record_type == _meta_type:
                LOGGER.warning(
                    "Duplicate metadata record at line %d in %s; ignoring",
                    line_no,
                    path,
                )
            elif record_type == _sample_type:
                try:
                    samples.append(_normalize(payload))
                except SensorFrameDecodeError as exc:
                    LOGGER.warning(
                        "Skipping malformed sample at line %d in %s: %s",
                        line_no,
                        path,
                        exc,
                        exc_info=True,
                    )
                    skipped += 1
            elif record_type == _end_type:
                end_record = _run_end_record_from_json(text)

    if skipped:
        LOGGER.warning("Skipped %d corrupt line(s) while reading %s", skipped, path)
    if metadata is None:
        raise ValueError(f"Run metadata missing in {path}")
    if not metadata.run_id:
        raise ValueError(f"Run metadata in {path} is missing required 'run_id' field")
    if end_record and not metadata.end_time_utc:
        end_time = end_record.end_time_utc
        if end_time:
            metadata.end_time_utc = str(end_time)
        else:
            LOGGER.warning(
                "Run end record in %s has no end_time_utc; metadata end time not updated",
                path,
            )
    return RunData(metadata=metadata, samples=samples, source_path=path)
