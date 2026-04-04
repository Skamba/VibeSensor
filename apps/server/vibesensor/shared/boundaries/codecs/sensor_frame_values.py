"""Shared SensorFrame field decoders used by mapping and row codecs."""

from __future__ import annotations

import math
from collections.abc import Sequence

from vibesensor.shared.boundaries.codecs.strength_metrics import strength_peaks_from_sequence
from vibesensor.shared.json_utils import safe_json_loads
from vibesensor.shared.types.json_types import JsonArray, JsonObject, is_json_array
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = [
    "SensorFrameDecodeError",
    "build_sensor_frame",
    "strict_optional_float",
    "strict_optional_int",
    "strength_bucket",
    "text_value",
    "top_peaks_from_value",
    "top_peaks_payload_from_row_value",
]

_TOP_PEAKS_KEY = "top_peaks"


class SensorFrameDecodeError(ValueError):
    """Raised when a raw boundary sample cannot be decoded to ``SensorFrame``."""

    def __init__(self, *, source: str, field: str, detail: str) -> None:
        super().__init__(f"{source}: {field} {detail}")
        self.source = source
        self.field = field
        self.detail = detail


def build_sensor_frame(
    *,
    run_id: str,
    timestamp_utc: str,
    t_s: float | None,
    client_id: str,
    client_name: str,
    location: str,
    sample_rate_hz: int | None,
    speed_kmh: float | None,
    gps_speed_kmh: float | None,
    speed_source: str,
    engine_rpm: float | None,
    engine_rpm_source: str,
    gear: float | None,
    final_drive_ratio: float | None,
    accel_x_g: float | None,
    accel_y_g: float | None,
    accel_z_g: float | None,
    dominant_freq_hz: float | None,
    dominant_axis: str,
    top_peaks: object,
    vibration_strength_db: float | None,
    strength_bucket: str | None,
    strength_peak_amp_g: float | None,
    strength_floor_amp_g: float | None,
    frames_dropped_total: int,
    queue_overflow_drops: int,
) -> SensorFrame:
    return SensorFrame(
        run_id=run_id,
        timestamp_utc=timestamp_utc,
        t_s=t_s,
        client_id=client_id,
        client_name=client_name,
        location=location,
        sample_rate_hz=sample_rate_hz,
        speed_kmh=speed_kmh,
        gps_speed_kmh=gps_speed_kmh,
        speed_source=speed_source,
        engine_rpm=engine_rpm,
        engine_rpm_source=engine_rpm_source,
        gear=gear,
        final_drive_ratio=final_drive_ratio,
        accel_x_g=accel_x_g,
        accel_y_g=accel_y_g,
        accel_z_g=accel_z_g,
        dominant_freq_hz=dominant_freq_hz,
        dominant_axis=dominant_axis,
        top_peaks=strength_peaks_from_sequence(top_peaks, max_items=10),
        vibration_strength_db=vibration_strength_db,
        strength_bucket=strength_bucket,
        strength_peak_amp_g=strength_peak_amp_g,
        strength_floor_amp_g=strength_floor_amp_g,
        frames_dropped_total=frames_dropped_total,
        queue_overflow_drops=queue_overflow_drops,
    )


def text_value(value: object) -> str:
    return str(value or "")


def strict_optional_float(value: object, *, field: str, source: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail="expected float-compatible value, got bool",
        )
    if not isinstance(value, int | float | str):
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail=f"expected float-compatible value, got {type(value).__name__}",
        )
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail=f"expected float-compatible value, got {type(value).__name__}",
        ) from exc
    return numeric if math.isfinite(numeric) else None


def strict_optional_int(value: object, *, field: str, source: str) -> int | None:
    numeric = strict_optional_float(value, field=field, source=source)
    if numeric is None:
        return None
    if numeric.is_integer():
        return int(numeric)
    raise SensorFrameDecodeError(
        source=source,
        field=field,
        detail=f"expected integer-compatible value, got {numeric}",
    )


def strength_bucket(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def top_peaks_from_value(
    value: object,
    *,
    strict: bool,
    source: str,
) -> tuple[JsonObject, ...] | tuple[object, ...]:
    if value in (None, "", ()):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        if strict:
            raise SensorFrameDecodeError(
                source=source,
                field=_TOP_PEAKS_KEY,
                detail=f"expected peak sequence, got {type(value).__name__}",
            )
        return ()
    return tuple(value)


def top_peaks_payload_from_row_value(value: object, *, source: str) -> JsonArray:
    if value in (None, ""):
        return []
    parsed = safe_json_loads(str(value), context=f"{source} {_TOP_PEAKS_KEY}")
    if parsed is None:
        raise SensorFrameDecodeError(
            source=source,
            field=_TOP_PEAKS_KEY,
            detail="contains invalid JSON",
        )
    if not is_json_array(parsed):
        raise SensorFrameDecodeError(
            source=source,
            field=_TOP_PEAKS_KEY,
            detail=f"expected JSON array, got {type(parsed).__name__}",
        )
    return parsed
