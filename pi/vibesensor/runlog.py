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


def default_units(*, accel_units: str = "g") -> dict[str, str]:
    return {
        "t_s": "s",
        "speed_kmh": "km/h",
        "gps_speed_kmh": "km/h",
        "accel_x_g": accel_units,
        "accel_y_g": accel_units,
        "accel_z_g": accel_units,
        "engine_rpm": "rpm",
        "gear": "ratio",
        "dominant_freq_hz": "Hz",
        "dominant_peak_amp_g": accel_units,
        "accel_magnitude_rms_g": accel_units,
        "accel_magnitude_p2p_g": accel_units,
        "vib_mag_rms_g": accel_units,
        "vib_mag_p2p_g": accel_units,
        "noise_floor_amp_p20_g": accel_units,
        "strength_floor_amp_g": accel_units,
        "strength_peak_band_rms_amp_g": accel_units,
        "strength_db": "dB",
        "strength_bucket": "band_key",
        "noise_floor_amp": accel_units,
    }


def default_amplitude_definitions(*, accel_units: str = "g") -> dict[str, dict[str, str]]:
    return {
        "accel_magnitude_rms_g": {
            "statistic": "RMS",
            "units": accel_units,
            "definition": "RMS of detrended vector vibration magnitude in the analysis window",
        },
        "accel_magnitude_p2p_g": {
            "statistic": "P2P",
            "units": accel_units,
            "definition": (
                "peak-to-peak of detrended vector vibration magnitude in the analysis window"
            ),
        },
        "vib_mag_rms_g": {
            "statistic": "RMS",
            "units": accel_units,
            "definition": "RMS of detrended vector vibration magnitude in the analysis window",
        },
        "vib_mag_p2p_g": {
            "statistic": "P2P",
            "units": accel_units,
            "definition": (
                "peak-to-peak of detrended vector vibration magnitude in the analysis window"
            ),
        },
        "noise_floor_amp": {
            "statistic": "Floor",
            "units": accel_units,
            "definition": (
                "Legacy alias of noise_floor_amp_p20_g "
                "(combined-spectrum 20th percentile, DC removed)"
            ),
        },
        "noise_floor_amp_p20_g": {
            "statistic": "Floor",
            "units": accel_units,
            "definition": "combined-spectrum noise floor amplitude (20th percentile, DC removed)",
        },
        "strength_floor_amp_g": {
            "statistic": "Floor",
            "units": accel_units,
            "definition": (
                "combined-spectrum floor amplitude after excluding strongest nearby peaks"
            ),
        },
        "strength_peak_band_rms_amp_g": {
            "statistic": "Peak band RMS",
            "units": accel_units,
            "definition": "RMS amplitude in ±1.2 Hz band around dominant combined-spectrum peak",
        },
        "strength_db": {
            "statistic": "dB above floor",
            "units": "dB",
            "definition": (
                "20*log10((strength_peak_band_rms_amp_g+eps)/(strength_floor_amp_g+eps)); "
                "eps=max(1e-9, strength_floor_amp_g*0.05)"
            ),
        },
        "strength_bucket": {
            "statistic": "Bucket",
            "units": "band_key",
            "definition": (
                "strength severity bucket derived from strength_db and peak band amplitude"
            ),
        },
        "dominant_peak_amp_g": {
            "statistic": "Peak",
            "units": accel_units,
            "definition": (
                "Legacy alias of strength_peak_band_rms_amp_g for backward compatibility"
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
    accel_scale_g_per_lsb: float | None,
    end_time_utc: str | None = None,
    incomplete_for_order_analysis: bool = False,
) -> dict[str, Any]:
    accel_units = "g" if accel_scale_g_per_lsb is not None else "raw_lsb"
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
        "accel_scale_g_per_lsb": accel_scale_g_per_lsb,
        "units": default_units(accel_units=accel_units),
        "amplitude_definitions": default_amplitude_definitions(accel_units=accel_units),
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
    normalized["vib_mag_rms_g"] = as_float_or_none(record.get("vib_mag_rms_g"))
    normalized["vib_mag_p2p_g"] = as_float_or_none(record.get("vib_mag_p2p_g"))
    normalized["noise_floor_amp_p20_g"] = as_float_or_none(
        record.get("noise_floor_amp_p20_g")
        if record.get("noise_floor_amp_p20_g") is not None
        else record.get("noise_floor_amp")
    )
    normalized["strength_floor_amp_g"] = as_float_or_none(
        record.get("strength_floor_amp_g")
        if record.get("strength_floor_amp_g") is not None
        else record.get("noise_floor_amp")
    )
    normalized["strength_peak_band_rms_amp_g"] = as_float_or_none(
        record.get("strength_peak_band_rms_amp_g")
        if record.get("strength_peak_band_rms_amp_g") is not None
        else record.get("dominant_peak_amp_g")
    )
    normalized["strength_db"] = as_float_or_none(record.get("strength_db"))
    normalized["strength_bucket"] = (
        str(record.get("strength_bucket"))
        if record.get("strength_bucket") not in (None, "")
        else None
    )
    # Legacy aliases: keep older readers working without recomputing strength metrics.
    normalized["noise_floor_amp"] = normalized["noise_floor_amp_p20_g"]
    normalized["dominant_peak_amp_g"] = normalized["strength_peak_band_rms_amp_g"]
    normalized["sample_rate_hz"] = as_int_or_none(record.get("sample_rate_hz"))
    top_peaks = record.get("top_peaks")
    normalized_peaks: list[dict[str, float]] = []
    if isinstance(top_peaks, list):
        for peak in top_peaks[:10]:
            if not isinstance(peak, dict):
                continue
            hz = as_float_or_none(peak.get("hz"))
            amp = as_float_or_none(peak.get("amp"))
            if hz is None or amp is None or hz <= 0:
                continue
            normalized_peaks.append({"hz": hz, "amp": amp})
    normalized["top_peaks"] = normalized_peaks
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
