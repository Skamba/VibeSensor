"""Canonical typed sample record shared across recording and persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["SensorFrame"]

_VSD_KEY: str = "vibration_strength_db"
_BUCKET_KEY: str = "strength_bucket"


def _normalize_peak_list(peaks_raw: object, *, max_items: int) -> list[dict[str, object]]:
    """Validate and normalize a raw peak list into canonical form."""
    from vibesensor.shared.json_utils import as_float_or_none

    normalized: list[dict[str, object]] = []
    if not isinstance(peaks_raw, list):
        return normalized
    for peak in peaks_raw[:max_items]:
        if not isinstance(peak, dict):
            continue
        hz = as_float_or_none(peak.get("hz"))
        amp = as_float_or_none(peak.get("amp"))
        if hz is None or amp is None or hz <= 0 or amp <= 0:
            continue
        normalized_peak: dict[str, object] = {"hz": hz, "amp": amp}
        peak_db = as_float_or_none(peak.get(_VSD_KEY))
        if peak_db is not None:
            normalized_peak[_VSD_KEY] = peak_db
        peak_bucket = peak.get(_BUCKET_KEY)
        if peak_bucket not in (None, ""):
            normalized_peak[_BUCKET_KEY] = str(peak_bucket)
        normalized.append(normalized_peak)
    return normalized


@dataclass(slots=True)
class SensorFrame:
    """A single sample record shared by run recording and persistence."""

    run_id: str
    timestamp_utc: str
    t_s: float | None
    client_id: str
    client_name: str
    location: str
    sample_rate_hz: int | None
    speed_kmh: float | None
    gps_speed_kmh: float | None
    speed_source: str
    engine_rpm: float | None
    engine_rpm_source: str
    gear: float | None
    final_drive_ratio: float | None
    accel_x_g: float | None
    accel_y_g: float | None
    accel_z_g: float | None
    dominant_freq_hz: float | None
    dominant_axis: str
    top_peaks: list[dict[str, object]]
    vibration_strength_db: float | None
    strength_bucket: str | None
    strength_peak_amp_g: float | None
    strength_floor_amp_g: float | None
    frames_dropped_total: int
    queue_overflow_drops: int

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "timestamp_utc": self.timestamp_utc,
            "t_s": self.t_s,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "location": self.location,
            "sample_rate_hz": self.sample_rate_hz,
            "speed_kmh": self.speed_kmh,
            "gps_speed_kmh": self.gps_speed_kmh,
            "speed_source": self.speed_source,
            "engine_rpm": self.engine_rpm,
            "engine_rpm_source": self.engine_rpm_source,
            "gear": self.gear,
            "final_drive_ratio": self.final_drive_ratio,
            "accel_x_g": self.accel_x_g,
            "accel_y_g": self.accel_y_g,
            "accel_z_g": self.accel_z_g,
            "dominant_freq_hz": self.dominant_freq_hz,
            "dominant_axis": self.dominant_axis,
            "top_peaks": list(self.top_peaks),
            _VSD_KEY: self.vibration_strength_db,
            _BUCKET_KEY: self.strength_bucket,
            "strength_peak_amp_g": self.strength_peak_amp_g,
            "strength_floor_amp_g": self.strength_floor_amp_g,
            "frames_dropped_total": self.frames_dropped_total,
            "queue_overflow_drops": self.queue_overflow_drops,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, object]) -> SensorFrame:
        """Normalize a raw sample dict (for example from JSONL or DB) into a SensorFrame."""
        from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none

        t_s = as_float_or_none(record.get("t_s"))
        speed_kmh = as_float_or_none(record.get("speed_kmh"))
        gps_speed_kmh = as_float_or_none(record.get("gps_speed_kmh"))
        accel_x_g = as_float_or_none(record.get("accel_x_g"))
        accel_y_g = as_float_or_none(record.get("accel_y_g"))
        accel_z_g = as_float_or_none(record.get("accel_z_g"))
        engine_rpm = as_float_or_none(record.get("engine_rpm"))
        gear = as_float_or_none(record.get("gear"))
        dominant_freq_hz = as_float_or_none(record.get("dominant_freq_hz"))
        vibration_strength_db = as_float_or_none(record.get(_VSD_KEY))
        raw_bucket = record.get(_BUCKET_KEY)
        strength_bucket = str(raw_bucket) if raw_bucket not in (None, "") else None
        strength_peak_amp_g = as_float_or_none(record.get("strength_peak_amp_g"))
        strength_floor_amp_g = as_float_or_none(record.get("strength_floor_amp_g"))
        sample_rate_hz = as_int_or_none(record.get("sample_rate_hz"))

        normalized_peaks = _normalize_peak_list(record.get("top_peaks"), max_items=10)

        return cls(
            run_id=str(record.get("run_id", "")),
            timestamp_utc=str(record.get("timestamp_utc", "")),
            t_s=t_s,
            client_id=str(record.get("client_id", "")),
            client_name=str(record.get("client_name", "")),
            location=str(record.get("location", "")),
            sample_rate_hz=sample_rate_hz,
            speed_kmh=speed_kmh,
            gps_speed_kmh=gps_speed_kmh,
            speed_source=str(record.get("speed_source", "")),
            engine_rpm=engine_rpm,
            engine_rpm_source=str(record.get("engine_rpm_source", "")),
            gear=gear,
            final_drive_ratio=as_float_or_none(record.get("final_drive_ratio")),
            accel_x_g=accel_x_g,
            accel_y_g=accel_y_g,
            accel_z_g=accel_z_g,
            dominant_freq_hz=dominant_freq_hz,
            dominant_axis=str(record.get("dominant_axis", "")),
            top_peaks=normalized_peaks,
            vibration_strength_db=vibration_strength_db,
            strength_bucket=strength_bucket,
            strength_peak_amp_g=strength_peak_amp_g,
            strength_floor_amp_g=strength_floor_amp_g,
            frames_dropped_total=as_int_or_none(record.get("frames_dropped_total")) or 0,
            queue_overflow_drops=as_int_or_none(record.get("queue_overflow_drops")) or 0,
        )
