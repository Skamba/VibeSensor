"""Domain model objects for VibeSensor backend.

Replaces ad-hoc dicts with typed dataclasses while keeping all external
JSON contracts (API responses, JSONL run schema, history DB blobs) stable.
"""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .analysis_settings import DEFAULT_ANALYSIS_SETTINGS, sanitize_settings
from .backend_types import (
    AnalysisSettingsPayload,
    CarConfigPayload,
    FallbackMode,
    SensorConfigPayload,
    SpeedSourceKind,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
)
from .constants import NUMERIC_TYPES
from .json_types import JsonObject, is_json_object
from .protocol import parse_client_id

_isfinite = math.isfinite
_LOGGER = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CAR_ASPECTS",
    "RUN_END_TYPE",
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RUN_SCHEMA_VERSION",
    "VALID_FALLBACK_MODES",
    "VALID_SPEED_SOURCES",
    "CarConfig",
    "RunMetadata",
    "SensorConfig",
    "SensorFrame",
    "SpeedSourceConfig",
    "as_float_or_none",
    "as_int_or_none",
    "new_car_id",
    "normalize_sensor_id",
    "sanitize_aspects",
]

# ---------------------------------------------------------------------------
# Shared helpers (previously inlined in runlog / metrics_log)
# ---------------------------------------------------------------------------

RUN_SCHEMA_VERSION: Final[str] = "v2-jsonl"
RUN_METADATA_TYPE: Final[str] = "run_metadata"
RUN_SAMPLE_TYPE: Final[str] = "sample"
RUN_END_TYPE: Final[str] = "run_end"

VALID_SPEED_SOURCES: tuple[str, ...] = ("gps", "obd2", "manual")
VALID_FALLBACK_MODES: tuple[str, ...] = ("manual",)

DEFAULT_CAR_ASPECTS: Final[MappingProxyType[str, float]] = MappingProxyType(
    DEFAULT_ANALYSIS_SETTINGS,
)


def as_float_or_none(value: object) -> float | None:
    """Return *value* as a finite float, or ``None`` for non-numeric / non-finite input."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not _isfinite(out):
        return None
    return out


def as_int_or_none(value: object) -> int | None:
    """Return *value* as a rounded int, or ``None`` for non-numeric / non-finite input."""
    out = as_float_or_none(value)
    if out is None:
        return None
    return round(out)


def _parse_manual_speed(value: object) -> float | None:
    """Return a positive, finite float speed (≤500 km/h) or None."""
    if isinstance(value, NUMERIC_TYPES):
        f = float(value)
        if _isfinite(f) and 0 < f <= 500:
            return f
    return None


def _parse_stale_timeout(value: object) -> float:
    """Return a stale-timeout value clamped to [3, 120], default 10."""
    if isinstance(value, NUMERIC_TYPES):
        return max(3.0, min(120.0, float(value)))
    return 10.0


def sanitize_aspects(raw: Mapping[str, object]) -> AnalysisSettingsPayload:
    """Sanitize car aspects using the canonical validation from analysis_settings."""
    sanitized = sanitize_settings(dict(raw), allowed_keys=DEFAULT_CAR_ASPECTS)
    return {key: float(value) for key, value in sanitized.items()}


def _as_str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _as_str_dict(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            return None
        out[key] = item
    return out


def _as_nested_str_dict(value: object) -> dict[str, dict[str, str]] | None:
    if not isinstance(value, Mapping):
        return None
    out: dict[str, dict[str, str]] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        nested = _as_str_dict(item)
        if nested is None:
            return None
        out[key] = nested
    return out


def _phase_metadata_from_raw(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return _default_phase_metadata()
    return {str(key): item for key, item in value.items()}


def _coerce_speed_source(value: object) -> SpeedSourceKind:
    if isinstance(value, str) and value in VALID_SPEED_SOURCES:
        if value == "obd2":
            return "obd2"
        if value == "manual":
            return "manual"
    return "gps"


def _coerce_fallback_mode(value: object) -> FallbackMode:
    return "manual"


def normalize_sensor_id(sensor_id: str) -> str:
    """Normalize a sensor MAC / hex string to canonical lowercase hex."""
    return str(parse_client_id(str(sensor_id)).hex())


# ---------------------------------------------------------------------------
# 1) CarConfig
# ---------------------------------------------------------------------------


def new_car_id() -> str:
    """Generate a new unique car configuration ID."""
    return str(uuid.uuid4())


@dataclass(slots=True)
class CarConfig:
    """Persisted vehicle profile (ID, name, type, geometry aspects, variant)."""

    id: str
    name: str
    type: str
    aspects: dict[str, float]
    variant: str | None

    # -- construction ----------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> CarConfig:
        """Construct a :class:`CarConfig` from a raw dict (e.g., loaded from JSON)."""
        car_id = str(data.get("id") or new_car_id())
        name = str(data.get("name") or "Unnamed Car").strip()[:64] or "Unnamed Car"
        car_type = str(data.get("type") or "sedan").strip()[:32] or "sedan"
        raw_aspects = data.get("aspects") or {}
        aspects = dict(DEFAULT_CAR_ASPECTS)
        if isinstance(raw_aspects, dict):
            aspects.update(sanitize_aspects(raw_aspects))
        raw_variant = data.get("variant")
        variant = (
            str(raw_variant).strip()[:64] if isinstance(raw_variant, str) and raw_variant else None
        )
        return cls(
            id=car_id,
            name=name,
            type=car_type,
            aspects=aspects,
            variant=variant or None,
        )

    # -- serialization ---------------------------------------------------------

    def to_dict(self) -> CarConfigPayload:
        """Serialise this car config to a plain dict for JSON persistence."""
        d: CarConfigPayload = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "aspects": dict(self.aspects),
        }
        if self.variant:
            d["variant"] = self.variant
        return d


# ---------------------------------------------------------------------------
# 2) SensorConfig
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SensorConfig:
    """Persisted configuration for a sensor node (ID, name, location)."""

    sensor_id: str
    name: str
    location: str

    @classmethod
    def from_dict(cls, sensor_id: str, data: Mapping[str, object]) -> SensorConfig:
        """Construct a :class:`SensorConfig` from *sensor_id* and a raw dict."""
        name = str(data.get("name") or sensor_id).strip()[:64]
        location = str(data.get("location") or "").strip()[:64]
        return cls(
            sensor_id=sensor_id,
            name=name or sensor_id,
            location=location,
        )

    def to_dict(self) -> SensorConfigPayload:
        """Serialise this sensor config to a plain dict."""
        return {"name": self.name, "location": self.location}


# ---------------------------------------------------------------------------
# 3) SpeedSourceConfig
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SpeedSourceConfig:
    """Speed source settings (GPS, OBD2, or manual) with fallback policy."""

    speed_source: SpeedSourceKind
    manual_speed_kph: float | None
    obd2_config: JsonObject
    stale_timeout_s: float
    fallback_mode: FallbackMode

    @classmethod
    def default(cls) -> SpeedSourceConfig:
        """Return a GPS-based default speed source config."""
        return cls(
            speed_source="gps",
            manual_speed_kph=None,
            obd2_config={},
            stale_timeout_s=10.0,
            fallback_mode="manual",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SpeedSourceConfig:
        """Construct a :class:`SpeedSourceConfig` from a raw dict (e.g., from API payload)."""
        speed_source = _coerce_speed_source(data.get("speedSource"))
        manual_speed_kph = _parse_manual_speed(data.get("manualSpeedKph"))
        obd2 = data.get("obd2Config")
        obd2_config = dict(obd2) if is_json_object(obd2) else {}
        raw_timeout = data.get("staleTimeoutS")
        stale_timeout_s = _parse_stale_timeout(raw_timeout)
        fallback_mode = _coerce_fallback_mode(data.get("fallbackMode"))
        return cls(
            speed_source=speed_source,
            manual_speed_kph=manual_speed_kph,
            obd2_config=obd2_config,
            stale_timeout_s=stale_timeout_s,
            fallback_mode=fallback_mode,
        )

    def to_dict(self) -> SpeedSourcePayload:
        """Serialise this speed source config to a plain dict for JSON persistence."""
        return {
            "speedSource": self.speed_source,
            "manualSpeedKph": self.manual_speed_kph,
            "obd2Config": dict(self.obd2_config),
            "staleTimeoutS": self.stale_timeout_s,
            "fallbackMode": self.fallback_mode,
        }

    def apply_update(self, data: SpeedSourceUpdatePayload) -> None:
        """Mutate in-place from an API update payload."""
        src = data.get("speedSource")
        if src is not None:
            self.speed_source = _coerce_speed_source(src)
        if "manualSpeedKph" in data:
            manual = data["manualSpeedKph"]
            if manual is None:
                self.manual_speed_kph = None
            else:
                self.manual_speed_kph = _parse_manual_speed(manual)
        obd2 = data.get("obd2Config")
        if is_json_object(obd2):
            self.obd2_config = dict(obd2)
        raw_timeout = data.get("staleTimeoutS")
        if raw_timeout is not None:
            self.stale_timeout_s = _parse_stale_timeout(raw_timeout)
        raw_fallback = data.get("fallbackMode")
        if raw_fallback is not None:
            self.fallback_mode = _coerce_fallback_mode(raw_fallback)


# ---------------------------------------------------------------------------
# 4) RunMetadata
# ---------------------------------------------------------------------------


def _default_units(*, accel_units: str = "g") -> dict[str, str]:
    return {
        "timestamp_utc": "iso8601",
        "t_s": "s",
        "speed_kmh": "km/h",
        "gps_speed_kmh": "km/h",
        "accel_x_g": accel_units,
        "accel_y_g": accel_units,
        "accel_z_g": accel_units,
        "engine_rpm": "rpm",
        "gear": "ratio",
        "dominant_freq_hz": "Hz",
        "vibration_strength_db": "dB",
        "strength_bucket": "band_key",
    }


def _default_amplitude_definitions(*, accel_units: str = "g") -> dict[str, dict[str, str]]:
    return {
        "vibration_strength_db": {
            "statistic": "dB above floor",
            "units": "dB",
            "definition": (
                "20*log10((peak_band_rms_amp_g+eps)/(floor_amp_g+eps)); "
                "eps=max(1e-9, floor_amp_g*0.05)"
            ),
        },
        "strength_bucket": {
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
    """Metadata record from the header of a JSONL run file."""

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
    def from_dict(cls, data: Mapping[str, object]) -> RunMetadata:
        accel_scale = data.get("accel_scale_g_per_lsb")
        accel_units = "g" if accel_scale is not None else "raw_lsb"
        run_id = str(data.get("run_id", ""))
        if not run_id:
            _LOGGER.warning("RunMetadata.from_dict: missing or empty run_id in record %r", data)
        return cls(
            record_type=str(data.get("record_type", RUN_METADATA_TYPE)),
            schema_version=str(data.get("schema_version", RUN_SCHEMA_VERSION)),
            run_id=run_id,
            start_time_utc=str(data.get("start_time_utc", "")),
            end_time_utc=_as_str_or_none(data.get("end_time_utc")),
            sensor_model=str(data.get("sensor_model", "unknown")),
            firmware_version=(str(data.get("firmware_version", "")).strip() or None),
            raw_sample_rate_hz=as_int_or_none(data.get("raw_sample_rate_hz")),
            feature_interval_s=as_float_or_none(data.get("feature_interval_s")),
            fft_window_size_samples=as_int_or_none(data.get("fft_window_size_samples")),
            fft_window_type=_as_str_or_none(data.get("fft_window_type")),
            peak_picker_method=str(data.get("peak_picker_method", "")),
            accel_scale_g_per_lsb=as_float_or_none(accel_scale),
            units=_as_str_dict(data.get("units")) or _default_units(accel_units=accel_units),
            amplitude_definitions=_as_nested_str_dict(data.get("amplitude_definitions"))
            or _default_amplitude_definitions(accel_units=accel_units),
            incomplete_for_order_analysis=bool(data.get("incomplete_for_order_analysis", False)),
            phase_metadata=_phase_metadata_from_raw(data.get("phase_metadata")),
        )

    def to_dict(self) -> dict[str, object]:
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

_VSD_KEY: str = "vibration_strength_db"
_BUCKET_KEY: str = "strength_bucket"


def _normalize_peak_list(peaks_raw: object, *, max_items: int) -> list[dict[str, object]]:
    """Validate and normalise a raw peak list into canonical form."""
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
    """A single sample/data record from a JSONL run file."""

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
    top_peaks_x: list[dict[str, object]]
    top_peaks_y: list[dict[str, object]]
    top_peaks_z: list[dict[str, object]]
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
            "top_peaks_x": list(self.top_peaks_x),
            "top_peaks_y": list(self.top_peaks_y),
            "top_peaks_z": list(self.top_peaks_z),
            _VSD_KEY: self.vibration_strength_db,
            _BUCKET_KEY: self.strength_bucket,
            "strength_peak_amp_g": self.strength_peak_amp_g,
            "strength_floor_amp_g": self.strength_floor_amp_g,
            "frames_dropped_total": self.frames_dropped_total,
            "queue_overflow_drops": self.queue_overflow_drops,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, object]) -> SensorFrame:
        """Normalize a raw sample dict (e.g. from JSONL or DB) into a SensorFrame."""
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
        normalized_peaks_x = _normalize_peak_list(record.get("top_peaks_x"), max_items=3)
        normalized_peaks_y = _normalize_peak_list(record.get("top_peaks_y"), max_items=3)
        normalized_peaks_z = _normalize_peak_list(record.get("top_peaks_z"), max_items=3)

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
            final_drive_ratio=as_float_or_none(record.get("final_drive_ratio")),
            accel_x_g=accel_x_g,
            accel_y_g=accel_y_g,
            accel_z_g=accel_z_g,
            dominant_freq_hz=dominant_freq_hz,
            dominant_axis=str(record.get("dominant_axis", "")),
            top_peaks=normalized_peaks,
            top_peaks_x=normalized_peaks_x,
            top_peaks_y=normalized_peaks_y,
            top_peaks_z=normalized_peaks_z,
            vibration_strength_db=vibration_strength_db,
            strength_bucket=strength_bucket,
            strength_peak_amp_g=strength_peak_amp_g,
            strength_floor_amp_g=strength_floor_amp_g,
            frames_dropped_total=as_int_or_none(record.get("frames_dropped_total")) or 0,
            queue_overflow_drops=as_int_or_none(record.get("queue_overflow_drops")) or 0,
        )
