"""Run-log I/O — reading, writing, and normalising JSONL run files.

Provides helpers for creating and reading metric run files in JSONL format,
plus normalisation helpers for canonical field name handling.

Canonical re-exports
--------------------
``as_float_or_none`` and ``as_int_or_none`` are defined in
``vibesensor.domain_models`` and re-exported here for convenience.
``utc_now_iso()`` is canonically defined in this module.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from .domain_models import (
    RUN_END_TYPE,
    RUN_METADATA_TYPE,
    RUN_SAMPLE_TYPE,
    RUN_SCHEMA_VERSION,
    RunMetadata,
    SensorFrame,
)
from .domain_models import as_float_or_none as _as_float_or_none
from .domain_models import as_int_or_none as _as_int_or_none
from .json_types import JsonObject, JsonValue

LOGGER = logging.getLogger(__name__)

_JSONL_SEPARATORS = (",", ":")


def _sanitize_non_finite(obj: JsonValue) -> JsonValue:
    """Recursively replace NaN/Inf floats with ``None`` for valid JSON output."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_non_finite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_non_finite(v) for v in obj]
    return obj


__all__ = [
    "RUN_END_TYPE",
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RUN_SCHEMA_VERSION",
    "RunData",
    "RunEndRecord",
    "append_jsonl_records",
    "as_float_or_none",
    "as_int_or_none",
    "bounded_sample",
    "create_run_end_record",
    "create_run_metadata",
    "normalize_sample_record",
    "parse_iso8601",
    "read_jsonl_run",
    "utc_now_iso",
]


@dataclass(slots=True)
class RunData:
    """Parsed contents of a JSONL run file: metadata, samples, and source path."""

    metadata: JsonObject
    samples: list[JsonObject]
    source_path: Path


class RunEndRecord(TypedDict):
    """Shape of a RUN_END record written to JSONL run logs."""

    record_type: str
    schema_version: str
    run_id: str
    end_time_utc: str


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def parse_iso8601(value: object) -> datetime | None:
    """Parse an ISO 8601 string into an aware ``datetime``, or return ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Ensure timezone-aware: assume UTC for naive timestamps
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


as_float_or_none = _as_float_or_none
as_int_or_none = _as_int_or_none


def create_run_metadata(
    *,
    run_id: str,
    start_time_utc: str,
    sensor_model: str,
    raw_sample_rate_hz: int | None,
    feature_interval_s: float | None,
    fft_window_size_samples: int | None,
    fft_window_type: str | None,
    peak_picker_method: str,
    accel_scale_g_per_lsb: float | None,
    firmware_version: str | None = None,
    end_time_utc: str | None = None,
    incomplete_for_order_analysis: bool = False,
) -> dict[str, object]:
    """Build and return a run-metadata dict from the supplied fields."""
    return RunMetadata.create(
        run_id=run_id,
        start_time_utc=start_time_utc,
        sensor_model=sensor_model,
        firmware_version=firmware_version,
        raw_sample_rate_hz=raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=fft_window_size_samples,
        fft_window_type=fft_window_type,
        peak_picker_method=peak_picker_method,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        end_time_utc=end_time_utc,
        incomplete_for_order_analysis=incomplete_for_order_analysis,
    ).to_dict()


def create_run_end_record(run_id: str, end_time_utc: str | None = None) -> RunEndRecord:
    """Build a RUN_END record dict to mark the end of a run in the log."""
    return RunEndRecord(
        record_type=RUN_END_TYPE,
        schema_version=RUN_SCHEMA_VERSION,
        run_id=run_id,
        end_time_utc=end_time_utc or utc_now_iso(),
    )


def normalize_sample_record(record: JsonObject) -> JsonObject:
    """Normalize a raw sample dict into canonical form.

    Delegates to :class:`SensorFrame` for field parsing.  Extra keys present
    in *record* but not part of the SensorFrame schema are preserved.
    """
    frame = SensorFrame.from_dict(record)
    normalized = dict(record)
    normalized.update(frame.to_dict())  # type: ignore[arg-type]  # dict[str, object] → JsonObject
    return normalized


def bounded_sample(
    samples: Iterator[JsonObject],
    *,
    max_items: int,
    total_hint: int = 0,
) -> tuple[list[JsonObject], int, int]:
    """Down-sample *samples* to at most *max_items*.

    When *total_hint* is available the stride is computed upfront so
    that we never over-collect and re-halve.

    Returns
    -------
    tuple[list[JsonObject], int, int]
        ``(kept_samples, total_count, final_stride)`` where
        *kept_samples* is the down-sampled list, *total_count* is the
        number of items consumed from the iterator, and *final_stride*
        is the stride factor that was applied.

    Raises
    ------
    ValueError
        If *max_items* is not a positive integer.

    """
    if max_items <= 0:
        raise ValueError(f"bounded_sample: max_items must be >= 1, got {max_items}")
    stride: int = max(1, -(-total_hint // max_items)) if total_hint > max_items else 1
    kept: list[JsonObject] = []
    total = 0
    for sample in samples:
        total += 1
        if (total - 1) % stride != 0:
            continue
        kept.append(sample)
        if len(kept) > max_items:
            kept = kept[::2]
            stride *= 2
    # Final trim: the halving loop can leave len(kept) == max_items + 1
    # in edge cases (e.g. max_items=1).  Guarantee the contract.
    if len(kept) > max_items:
        kept = kept[:max_items]
    return kept, total, stride


def append_jsonl_records(
    path: Path,
    records: Iterable[JsonObject],
    *,
    durable: bool = False,
    durable_every_records: int = 100,
) -> None:
    """Append *records* as JSONL lines to *path*, optionally with fsync durability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cadence = max(1, int(durable_every_records))
    _dumps = json.dumps
    _seps = _JSONL_SEPARATORS
    with path.open("a", encoding="utf-8") as f:
        for index, record in enumerate(records, start=1):
            try:
                line = _dumps(record, ensure_ascii=False, allow_nan=False, separators=_seps)
            except ValueError:
                # NaN/Inf values — sanitize to null so the output is always
                # valid JSON and downstream consumers can parse it safely.
                LOGGER.warning(
                    "Record %d contains non-finite float; sanitising NaN/Inf to null",
                    index,
                )
                line = _dumps(
                    _sanitize_non_finite(record),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=_seps,
                )
            except TypeError as exc:
                # Non-serialisable value (datetime, bytes, set, …). Coerce
                # to string representation so we never silently drop a
                # record mid-batch or leave a partial trailing line.
                LOGGER.warning(
                    "Record %d contains non-serialisable value (%s); using default fallback",
                    index,
                    exc,
                )
                line = _dumps(
                    _sanitize_non_finite(record),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=_seps,
                    default=str,
                )
            f.write(line + "\n")
            if durable and (index % cadence) == 0:
                f.flush()
                os.fsync(f.fileno())
        if durable:
            f.flush()
            os.fsync(f.fileno())


def read_jsonl_run(path: Path) -> RunData:
    """Read a JSONL run file and return parsed metadata and sample records."""
    if not path.exists():
        raise FileNotFoundError(path)

    metadata: JsonObject | None = None
    end_record: JsonObject | None = None
    samples: list[JsonObject] = []
    skipped = 0
    _loads = json.loads
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
                payload = _loads(text)
            except json.JSONDecodeError as exc:
                LOGGER.warning(
                    "Skipping corrupt JSONL line %d in %s: %s",
                    line_no,
                    path,
                    exc,
                )
                skipped += 1
                continue
            if not isinstance(payload, dict):
                continue
            record_type = str(payload.get("record_type", ""))
            if record_type == _meta_type and metadata is None:
                metadata = payload
            elif record_type == _meta_type:
                LOGGER.warning(
                    "Duplicate metadata record at line %d in %s; ignoring",
                    line_no,
                    path,
                )
            elif record_type == _sample_type:
                try:
                    samples.append(_normalize(payload))
                except (KeyError, ValueError, TypeError) as exc:
                    LOGGER.warning(
                        "Skipping malformed sample at line %d in %s: %s",
                        line_no,
                        path,
                        exc,
                        exc_info=True,
                    )
                    skipped += 1
            elif record_type == _end_type:
                end_record = payload

    if skipped:
        LOGGER.warning("Skipped %d corrupt line(s) while reading %s", skipped, path)
    if metadata is None:
        raise ValueError(f"Run metadata missing in {path}")
    if not metadata.get("run_id"):
        raise ValueError(f"Run metadata in {path} is missing required 'run_id' field")
    if end_record and not metadata.get("end_time_utc"):
        end_time = end_record.get("end_time_utc")
        if end_time:
            metadata["end_time_utc"] = end_time
        else:
            LOGGER.warning(
                "Run end record in %s has no end_time_utc; metadata end time not updated",
                path,
            )
    return RunData(metadata=metadata, samples=samples, source_path=path)
