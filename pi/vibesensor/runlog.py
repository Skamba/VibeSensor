from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_SCHEMA_VERSION = "v2-jsonl"

RUN_METADATA_TYPE = "run_metadata"
RUN_SAMPLE_TYPE = "sample"
RUN_END_TYPE = "run_end"

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


def as_float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def as_int_or_none(value: object) -> int | None:
    out = as_float_or_none(value)
    if out is None:
        return None
    return int(round(out))


def default_units() -> dict[str, str]:
    return {
        "t_s": "s",
        "speed_kmh": "km/h",
        "gps_speed_kmh": "km/h",
        "accel_x_g": "g",
        "accel_y_g": "g",
        "accel_z_g": "g",
        "engine_rpm": "rpm",
        "gear": "ratio",
        "dominant_freq_hz": "Hz",
        "dominant_peak_amp_g": "g",
        "accel_magnitude_rms_g": "g",
        "accel_magnitude_p2p_g": "g",
    }


def default_amplitude_definitions() -> dict[str, dict[str, str]]:
    return {
        "accel_magnitude_rms_g": {
            "statistic": "RMS",
            "units": "g",
            "definition": "sqrt((x_rms^2 + y_rms^2 + z_rms^2) / 3) from latest analysis window",
        },
        "accel_magnitude_p2p_g": {
            "statistic": "P2P",
            "units": "g",
            "definition": "maximum per-axis peak-to-peak acceleration from latest analysis window",
        },
        "dominant_peak_amp_g": {
            "statistic": "Peak",
            "units": "g",
            "definition": (
                "largest single-sided FFT peak amplitude across axes "
                "from the latest FFT block"
            ),
        },
    }


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
    end_time_utc: str | None = None,
    incomplete_for_order_analysis: bool = False,
) -> dict[str, Any]:
    return {
        "record_type": RUN_METADATA_TYPE,
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "start_time_utc": start_time_utc,
        "end_time_utc": end_time_utc,
        "sensor_model": sensor_model,
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "feature_interval_s": feature_interval_s,
        "fft_window_size_samples": fft_window_size_samples,
        "fft_window_type": fft_window_type,
        "peak_picker_method": peak_picker_method,
        "units": default_units(),
        "amplitude_definitions": default_amplitude_definitions(),
        "incomplete_for_order_analysis": bool(incomplete_for_order_analysis),
    }


def create_run_end_record(run_id: str, end_time_utc: str | None = None) -> dict[str, Any]:
    return {
        "record_type": RUN_END_TYPE,
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "end_time_utc": end_time_utc or utc_now_iso(),
    }


def normalize_sample_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized["record_type"] = RUN_SAMPLE_TYPE
    normalized["t_s"] = as_float_or_none(record.get("t_s"))
    normalized["speed_kmh"] = as_float_or_none(record.get("speed_kmh"))
    normalized["gps_speed_kmh"] = as_float_or_none(record.get("gps_speed_kmh"))
    normalized["accel_x_g"] = as_float_or_none(record.get("accel_x_g"))
    normalized["accel_y_g"] = as_float_or_none(record.get("accel_y_g"))
    normalized["accel_z_g"] = as_float_or_none(record.get("accel_z_g"))
    normalized["engine_rpm"] = as_float_or_none(record.get("engine_rpm"))
    normalized["gear"] = as_float_or_none(record.get("gear"))
    normalized["dominant_freq_hz"] = as_float_or_none(record.get("dominant_freq_hz"))
    normalized["dominant_peak_amp_g"] = as_float_or_none(record.get("dominant_peak_amp_g"))
    normalized["accel_magnitude_rms_g"] = as_float_or_none(record.get("accel_magnitude_rms_g"))
    normalized["accel_magnitude_p2p_g"] = as_float_or_none(record.get("accel_magnitude_p2p_g"))
    normalized["sample_rate_hz"] = as_int_or_none(record.get("sample_rate_hz"))
    return normalized


def append_jsonl_records(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")))
            f.write("\n")


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
