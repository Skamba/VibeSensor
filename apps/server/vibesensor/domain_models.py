"""Domain model objects for VibeSensor backend.

Replaces ad-hoc dicts with typed dataclasses while keeping all external
JSON contracts (API responses, JSONL run schema, history DB blobs) stable.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from vibesensor_shared.contracts import METRIC_FIELDS, REPORT_FIELDS

from .analysis_settings import DEFAULT_ANALYSIS_SETTINGS, sanitize_settings
from .protocol import parse_client_id

# ---------------------------------------------------------------------------
# Shared helpers (previously inlined in runlog / metrics_log)
# ---------------------------------------------------------------------------

RUN_SCHEMA_VERSION = "v2-jsonl"
RUN_METADATA_TYPE = "run_metadata"
RUN_SAMPLE_TYPE = "sample"
RUN_END_TYPE = "run_end"

VALID_SPEED_SOURCES: tuple[str, ...] = ("gps", "obd2", "manual")
VALID_FALLBACK_MODES: tuple[str, ...] = ("manual",)

DEFAULT_CAR_ASPECTS: dict[str, float] = dict(DEFAULT_ANALYSIS_SETTINGS)


def _as_float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _as_int_or_none(value: object) -> int | None:
    out = _as_float_or_none(value)
    if out is None:
        return None
    return int(round(out))


def _parse_manual_speed(value: Any) -> float | None:
    """Return a positive, finite float speed (≤500 km/h) or None."""
    if isinstance(value, (int, float)):
        f = float(value)
        if math.isfinite(f) and 0 < f <= 500:
            return f
    return None


def _parse_stale_timeout(value: Any) -> float:
    """Return a stale-timeout value clamped to [3, 120], default 10."""
    if isinstance(value, (int, float)):
        return max(3.0, min(120.0, float(value)))
    return 10.0


def _sanitize_aspects(raw: dict[str, Any]) -> dict[str, float]:
    """Sanitize car aspects using the canonical validation from analysis_settings."""
    return sanitize_settings(raw, allowed_keys=DEFAULT_CAR_ASPECTS)


def normalize_sensor_id(sensor_id: str) -> str:
    """Normalize a sensor MAC / hex string to canonical lowercase hex."""
    return parse_client_id(str(sensor_id)).hex()


# ---------------------------------------------------------------------------
# 1) CarConfig
# ---------------------------------------------------------------------------


def _new_car_id() -> str:
    return str(uuid.uuid4())


@dataclass(slots=True)
class CarConfig:
    id: str
    name: str
    type: str
    aspects: dict[str, float]

    # -- construction ----------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CarConfig:
        car_id = str(data.get("id") or _new_car_id())
        name = str(data.get("name") or "Unnamed Car").strip()[:64]
        car_type = str(data.get("type") or "sedan").strip()[:32]
        raw_aspects = data.get("aspects") or {}
        aspects = dict(DEFAULT_CAR_ASPECTS)
        if isinstance(raw_aspects, dict):
            aspects.update(_sanitize_aspects(raw_aspects))
        return cls(
            id=car_id,
            name=name or "Unnamed Car",
            type=car_type or "sedan",
            aspects=aspects,
        )

    @classmethod
    def default(cls) -> CarConfig:
        return cls.from_dict({"id": _new_car_id(), "name": "Default Car", "type": "sedan"})

    # -- serialization ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "aspects": dict(self.aspects),
        }


# ---------------------------------------------------------------------------
# 2) SensorConfig
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SensorConfig:
    sensor_id: str
    name: str
    location: str

    @classmethod
    def from_dict(cls, sensor_id: str, data: dict[str, Any]) -> SensorConfig:
        name = str(data.get("name") or sensor_id).strip()[:64]
        location = str(data.get("location") or "").strip()[:64]
        return cls(
            sensor_id=sensor_id,
            name=name or sensor_id,
            location=location,
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "location": self.location}


# ---------------------------------------------------------------------------
# 3) SpeedSourceConfig
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SpeedSourceConfig:
    speed_source: str  # Literal values: "gps", "obd2", "manual"
    manual_speed_kph: float | None
    obd2_config: dict[str, Any]
    stale_timeout_s: float
    fallback_mode: str

    @classmethod
    def default(cls) -> SpeedSourceConfig:
        return cls(
            speed_source="gps",
            manual_speed_kph=None,
            obd2_config={},
            stale_timeout_s=10.0,
            fallback_mode="manual",
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeedSourceConfig:
        src = str(data.get("speedSource") or data.get("speed_source") or "gps")
        speed_source = src if src in VALID_SPEED_SOURCES else "gps"
        manual_speed_kph = _parse_manual_speed(
            data.get("manualSpeedKph") or data.get("manual_speed_kph")
        )
        obd2 = data.get("obd2Config") or data.get("obd2_config")
        obd2_config = obd2 if isinstance(obd2, dict) else {}
        raw_timeout = data.get("staleTimeoutS") or data.get("stale_timeout_s")
        stale_timeout_s = _parse_stale_timeout(raw_timeout)
        raw_fallback = data.get("fallbackMode") or data.get("fallback_mode")
        fallback_mode = (
            str(raw_fallback)
            if isinstance(raw_fallback, str) and raw_fallback in VALID_FALLBACK_MODES
            else "manual"
        )
        return cls(
            speed_source=speed_source,
            manual_speed_kph=manual_speed_kph,
            obd2_config=obd2_config,
            stale_timeout_s=stale_timeout_s,
            fallback_mode=fallback_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "speedSource": self.speed_source,
            "manualSpeedKph": self.manual_speed_kph,
            "obd2Config": dict(self.obd2_config),
            "staleTimeoutS": self.stale_timeout_s,
            "fallbackMode": self.fallback_mode,
        }

    def apply_update(self, data: dict[str, Any]) -> None:
        """Mutate in-place from an API update payload."""
        src = data.get("speedSource")
        if isinstance(src, str) and src in VALID_SPEED_SOURCES:
            self.speed_source = src
        manual = data.get("manualSpeedKph")
        if manual is None:
            self.manual_speed_kph = None
        else:
            self.manual_speed_kph = _parse_manual_speed(manual)
        obd2 = data.get("obd2Config")
        if isinstance(obd2, dict):
            self.obd2_config = obd2
        raw_timeout = data.get("staleTimeoutS")
        if raw_timeout is not None:
            self.stale_timeout_s = _parse_stale_timeout(raw_timeout)
        raw_fallback = data.get("fallbackMode")
        if isinstance(raw_fallback, str) and raw_fallback in VALID_FALLBACK_MODES:
            self.fallback_mode = raw_fallback


# ---------------------------------------------------------------------------
# 4) RunMetadata
# ---------------------------------------------------------------------------


def _default_units(*, accel_units: str = "g") -> dict[str, str]:
    return {
        REPORT_FIELDS["timestamp_utc"]: "iso8601",
        "t_s": "s",
        REPORT_FIELDS["speed_kmh"]: "km/h",
        "gps_speed_kmh": "km/h",
        "accel_x_g": accel_units,
        "accel_y_g": accel_units,
        "accel_z_g": accel_units,
        "engine_rpm": "rpm",
        "gear": "ratio",
        REPORT_FIELDS["dominant_freq_hz"]: "Hz",
        METRIC_FIELDS["vibration_strength_db"]: "dB",
        METRIC_FIELDS["strength_bucket"]: "band_key",
    }


def _default_amplitude_definitions(*, accel_units: str = "g") -> dict[str, dict[str, str]]:
    return {
        METRIC_FIELDS["vibration_strength_db"]: {
            "statistic": "dB above floor",
            "units": "dB",
            "definition": (
                "20*log10((peak_band_rms_amp_g+eps)/(floor_amp_g+eps)); "
                "eps=max(1e-9, floor_amp_g*0.05)"
            ),
        },
        METRIC_FIELDS["strength_bucket"]: {
            "statistic": "Bucket",
            "units": "band_key",
            "definition": "strength severity bucket derived from vibration_strength_db",
        },
    }


def _default_phase_metadata() -> dict[str, object]:
    return {
        "version": "v1",
        "idle_speed_kmh_max": 3.0,
        "acceleration_threshold_kmh_s": 1.5,
        "deceleration_threshold_kmh_s": -1.5,
        "coast_down_speed_kmh_max": 15.0,
        "labels": ["idle", "acceleration", "cruise", "deceleration", "coast_down"],
    }


@dataclass(slots=True)
class RunMetadata:
    record_type: str
    schema_version: str
    run_id: str
    start_time_utc: str
    end_time_utc: str | None
    sensor_model: str
    firmware_version: str | None
    raw_sample_rate_hz: int | None
    feature_interval_s: float | None
    fft_window_size_samples: int | None
    fft_window_type: str | None
    peak_picker_method: str
    accel_scale_g_per_lsb: float | None
    units: dict[str, str]
    amplitude_definitions: dict[str, dict[str, str]]
    incomplete_for_order_analysis: bool
    phase_metadata: dict[str, object]

    @classmethod
    def create(
        cls,
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
    ) -> RunMetadata:
        accel_units = "g" if accel_scale_g_per_lsb is not None else "raw_lsb"
        return cls(
            record_type=RUN_METADATA_TYPE,
            schema_version=RUN_SCHEMA_VERSION,
            run_id=run_id,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
            sensor_model=sensor_model,
            firmware_version=firmware_version,
            raw_sample_rate_hz=raw_sample_rate_hz,
            feature_interval_s=feature_interval_s,
            fft_window_size_samples=fft_window_size_samples,
            fft_window_type=fft_window_type,
            peak_picker_method=peak_picker_method,
            accel_scale_g_per_lsb=accel_scale_g_per_lsb,
            units=_default_units(accel_units=accel_units),
            amplitude_definitions=_default_amplitude_definitions(accel_units=accel_units),
            incomplete_for_order_analysis=bool(incomplete_for_order_analysis),
            phase_metadata=_default_phase_metadata(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunMetadata:
        accel_scale = data.get("accel_scale_g_per_lsb")
        accel_units = "g" if accel_scale is not None else "raw_lsb"
        return cls(
            record_type=str(data.get("record_type", RUN_METADATA_TYPE)),
            schema_version=str(data.get("schema_version", RUN_SCHEMA_VERSION)),
            run_id=str(data.get("run_id", "")),
            start_time_utc=str(data.get("start_time_utc", "")),
            end_time_utc=data.get("end_time_utc"),
            sensor_model=str(data.get("sensor_model", "unknown")),
            firmware_version=(str(data.get("firmware_version", "")).strip() or None),
            raw_sample_rate_hz=_as_int_or_none(data.get("raw_sample_rate_hz")),
            feature_interval_s=_as_float_or_none(data.get("feature_interval_s")),
            fft_window_size_samples=_as_int_or_none(data.get("fft_window_size_samples")),
            fft_window_type=data.get("fft_window_type"),
            peak_picker_method=str(data.get("peak_picker_method", "")),
            accel_scale_g_per_lsb=_as_float_or_none(accel_scale),
            units=data.get("units") or _default_units(accel_units=accel_units),
            amplitude_definitions=data.get("amplitude_definitions")
            or _default_amplitude_definitions(accel_units=accel_units),
            incomplete_for_order_analysis=bool(data.get("incomplete_for_order_analysis", False)),
            phase_metadata=(
                dict(data.get("phase_metadata"))
                if isinstance(data.get("phase_metadata"), dict)
                else _default_phase_metadata()
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "sensor_model": self.sensor_model,
            "firmware_version": self.firmware_version,
            "raw_sample_rate_hz": self.raw_sample_rate_hz,
            "feature_interval_s": self.feature_interval_s,
            "fft_window_size_samples": self.fft_window_size_samples,
            "fft_window_type": self.fft_window_type,
            "peak_picker_method": self.peak_picker_method,
            "accel_scale_g_per_lsb": self.accel_scale_g_per_lsb,
            "units": dict(self.units),
            "amplitude_definitions": {k: dict(v) for k, v in self.amplitude_definitions.items()},
            "incomplete_for_order_analysis": self.incomplete_for_order_analysis,
            "phase_metadata": dict(self.phase_metadata),
        }


# ---------------------------------------------------------------------------
# 5) SensorFrame
# ---------------------------------------------------------------------------

_VSD_KEY: str = METRIC_FIELDS["vibration_strength_db"]
_BUCKET_KEY: str = METRIC_FIELDS["strength_bucket"]


@dataclass(slots=True)
class SensorFrame:
    record_type: str
    schema_version: str
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
            "record_type": self.record_type,
            "schema_version": self.schema_version,
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
    def from_dict(cls, record: dict[str, Any]) -> SensorFrame:
        """Normalize a raw sample dict (e.g. from JSONL or DB) into a SensorFrame.

        Handles backward-compat rename ``strength_db`` -> ``vibration_strength_db``.
        """
        t_s = _as_float_or_none(record.get("t_s"))
        speed_kmh = _as_float_or_none(record.get("speed_kmh"))
        gps_speed_kmh = _as_float_or_none(record.get("gps_speed_kmh"))
        accel_x_g = _as_float_or_none(record.get("accel_x_g"))
        accel_y_g = _as_float_or_none(record.get("accel_y_g"))
        accel_z_g = _as_float_or_none(record.get("accel_z_g"))
        engine_rpm = _as_float_or_none(record.get("engine_rpm"))
        gear = _as_float_or_none(record.get("gear"))
        dominant_freq_hz = _as_float_or_none(record.get(REPORT_FIELDS["dominant_freq_hz"]))
        # Backward-compat: old runs wrote "strength_db"; new runs write "vibration_strength_db".
        vibration_strength_db = _as_float_or_none(record.get(_VSD_KEY) or record.get("strength_db"))
        raw_bucket = record.get(_BUCKET_KEY)
        strength_bucket = str(raw_bucket) if raw_bucket not in (None, "") else None
        strength_peak_amp_g = _as_float_or_none(record.get("strength_peak_amp_g"))
        strength_floor_amp_g = _as_float_or_none(record.get("strength_floor_amp_g"))
        sample_rate_hz = _as_int_or_none(record.get("sample_rate_hz"))

        # Normalize top_peaks
        top_peaks_raw = record.get("top_peaks")
        normalized_peaks: list[dict[str, object]] = []
        if isinstance(top_peaks_raw, list):
            for peak in top_peaks_raw[:10]:
                if not isinstance(peak, dict):
                    continue
                hz = _as_float_or_none(peak.get("hz"))
                amp = _as_float_or_none(peak.get("amp"))
                if hz is None or amp is None or hz <= 0:
                    continue
                normalized_peak: dict[str, object] = {"hz": hz, "amp": amp}
                peak_db = _as_float_or_none(peak.get(METRIC_FIELDS["vibration_strength_db"]))
                if peak_db is not None:
                    normalized_peak[METRIC_FIELDS["vibration_strength_db"]] = peak_db
                peak_bucket = peak.get(METRIC_FIELDS["strength_bucket"])
                if peak_bucket not in (None, ""):
                    normalized_peak[METRIC_FIELDS["strength_bucket"]] = str(peak_bucket)
                normalized_peaks.append(normalized_peak)

        return cls(
            record_type=RUN_SAMPLE_TYPE,
            schema_version=str(record.get("schema_version", RUN_SCHEMA_VERSION)),
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
            final_drive_ratio=_as_float_or_none(record.get("final_drive_ratio")),
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
            frames_dropped_total=int(record.get("frames_dropped_total") or 0),
            queue_overflow_drops=int(record.get("queue_overflow_drops") or 0),
        )
