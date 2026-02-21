from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain_models import (
    RUN_END_TYPE,
    RUN_METADATA_TYPE,
    RUN_SAMPLE_TYPE,
    RUN_SCHEMA_VERSION,
    RunMetadata,
    SensorFrame,
    _as_float_or_none,
    _as_int_or_none,
    _default_amplitude_definitions,
    _default_units,
)

__all__ = [
    "RUN_SCHEMA_VERSION",
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RUN_END_TYPE",
    "RunData",
    "utc_now_iso",
    "parse_iso8601",
    "as_float_or_none",
    "as_int_or_none",
    "default_units",
    "default_amplitude_definitions",
    "create_run_metadata",
    "create_run_end_record",
    "normalize_sample_record",
    "append_jsonl_records",
    "read_jsonl_run",
]

REQUIRED_SAMPLE_FIELDS = (
    "t_s",
    "speed_kmh",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
)


@dataclass(slots=True)
class RunData:
    metadata: dict[str, Any]
    samples: list[dict[str, Any]]
    source_path: Path


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso8601(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


as_float_or_none = _as_float_or_none
as_int_or_none = _as_int_or_none
default_units = _default_units
default_amplitude_definitions = _default_amplitude_definitions


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
    end_time_utc: str | None = None,
    incomplete_for_order_analysis: bool = False,
) -> dict[str, Any]:
    return RunMetadata.create(
        run_id=run_id,
        start_time_utc=start_time_utc,
        sensor_model=sensor_model,
        raw_sample_rate_hz=raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=fft_window_size_samples,
        fft_window_type=fft_window_type,
        peak_picker_method=peak_picker_method,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
        end_time_utc=end_time_utc,
        incomplete_for_order_analysis=incomplete_for_order_analysis,
    ).to_dict()


def create_run_end_record(run_id: str, end_time_utc: str | None = None) -> dict[str, Any]:
    return {
        "record_type": RUN_END_TYPE,
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "end_time_utc": end_time_utc or utc_now_iso(),
    }


def normalize_sample_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw sample dict into canonical form.

    Delegates to :class:`SensorFrame` for field parsing and renames
    (``strength_db`` -> ``vibration_strength_db``).  Extra keys present
    in *record* but not part of the SensorFrame schema are preserved.
    """
    frame = SensorFrame.from_dict(record)
    normalized = dict(record)
    normalized.update(frame.to_dict())
    return normalized


def append_jsonl_records(
    path: Path,
    records: Iterable[dict[str, Any]],
    *,
    durable: bool = False,
    durable_every_records: int = 100,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cadence = max(1, int(durable_every_records))
    with path.open("a", encoding="utf-8") as f:
        for index, record in enumerate(records, start=1):
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            if durable and (index % cadence) == 0:
                f.flush()
                os.fsync(f.fileno())
        if durable:
            f.flush()
            os.fsync(f.fileno())


def read_jsonl_run(path: Path) -> RunData:
    if not path.exists():
        raise FileNotFoundError(path)

    metadata: dict[str, Any] | None = None
    end_record: dict[str, Any] | None = None
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                continue
            record_type = str(payload.get("record_type", ""))
            if record_type == RUN_METADATA_TYPE and metadata is None:
                metadata = payload
            elif record_type == RUN_SAMPLE_TYPE:
                samples.append(normalize_sample_record(payload))
            elif record_type == RUN_END_TYPE:
                end_record = payload

    if metadata is None:
        raise ValueError(f"Run metadata missing in {path}")
    if end_record and not metadata.get("end_time_utc"):
        metadata["end_time_utc"] = end_record.get("end_time_utc")
    return RunData(metadata=metadata, samples=samples, source_path=path)
