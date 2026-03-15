"""Shared typed contracts for backend settings, history, and status boundaries."""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, NotRequired, TypeAlias, TypedDict

from vibesensor.domain.sensing.speed_source import SpeedSourceKind as SpeedSourceKind
from vibesensor.infra.config.analysis_settings import DEFAULT_ANALYSIS_SETTINGS, sanitize_settings
from vibesensor.infra.config.constants import NUMERIC_TYPES
from vibesensor.shared.types.json import JsonObject, is_json_object

if TYPE_CHECKING:
    from vibesensor.domain import Car, Sensor, SpeedSource

_isfinite = math.isfinite
_LOGGER = logging.getLogger(__name__)

__all__ = [
    "CarConfig",
    "CarConfigPayload",
    "CarConfigUpdatePayload",
    "CarsPayload",
    "DEFAULT_CAR_ASPECTS",
    "HistoryRunListEntryPayload",
    "HistoryRunPayload",
    "RUN_END_TYPE",
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RUN_SCHEMA_VERSION",
    "RunMetadata",
    "SensorConfig",
    "SensorConfigPayload",
    "SensorConfigUpdatePayload",
    "SettingsSnapshotPayload",
    "SpeedSourceConfig",
    "SpeedSourcePayload",
    "SpeedSourceUpdatePayload",
    "VALID_FALLBACK_MODES",
    "VALID_SPEED_SOURCES",
    "new_car_id",
    "sanitize_aspects",
]

AnalysisSettingsPayload: TypeAlias = dict[str, float]
LanguageCode: TypeAlias = Literal["en", "nl"]
SpeedUnitCode: TypeAlias = Literal["kmh", "mps"]
FallbackMode: TypeAlias = Literal["manual"]
ResolvedSpeedSource: TypeAlias = Literal["gps", "manual", "fallback_manual", "none"]


class CarConfigUpdatePayload(TypedDict, total=False):
    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: str


class CarConfigPayload(TypedDict):
    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: NotRequired[str]


class CarsPayload(TypedDict):
    cars: list[CarConfigPayload]
    activeCarId: str | None


class SensorConfigPayload(TypedDict):
    name: str
    location_code: str


class SensorConfigUpdatePayload(TypedDict, total=False):
    name: str
    location_code: str


SensorsByMacPayload: TypeAlias = dict[str, SensorConfigPayload]


class SpeedSourceUpdatePayload(TypedDict, total=False):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    obd2Config: JsonObject
    staleTimeoutS: float
    fallbackMode: FallbackMode


class SpeedSourcePayload(TypedDict):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    obd2Config: JsonObject
    staleTimeoutS: float
    fallbackMode: FallbackMode


class SettingsSnapshotPayload(SpeedSourcePayload):
    cars: list[CarConfigPayload]
    activeCarId: str | None
    language: LanguageCode
    speedUnit: SpeedUnitCode
    sensorsByMac: SensorsByMacPayload


class HistoryRunListEntryPayload(TypedDict, total=False):
    """Typed record returned by :meth:`HistoryRunService.list_runs`.

    Subset of :class:`HistoryRunPayload` without ``metadata``/``analysis``.
    """

    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None
    created_at: str
    sample_count: int
    error_message: str


class HistoryRunPayload(TypedDict, total=False):
    """Typed record returned by :meth:`HistoryRunService.get_run`.

    Acts as the history-record boundary type used throughout the service
    layer.  All ``history_services/`` methods return this (or its list
    subset) instead of raw dicts.
    """

    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None
    metadata: JsonObject
    analysis: JsonObject
    analysis_corrupt: bool
    error_message: str
    created_at: str
    sample_count: int
    analysis_started_at: str
    analysis_completed_at: str


# ---------------------------------------------------------------------------
# Run schema constants
# ---------------------------------------------------------------------------

RUN_SCHEMA_VERSION: Final[str] = "v2-jsonl"
RUN_METADATA_TYPE: Final[str] = "run_metadata"
RUN_SAMPLE_TYPE: Final[str] = "sample"
RUN_END_TYPE: Final[str] = "run_end"

VALID_SPEED_SOURCES: tuple[str, ...] = tuple(SpeedSourceKind)
VALID_FALLBACK_MODES: tuple[str, ...] = ("manual",)

DEFAULT_CAR_ASPECTS: Final[MappingProxyType[str, float]] = MappingProxyType(
    DEFAULT_ANALYSIS_SETTINGS,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_manual_speed(value: object) -> float | None:
    """Return a positive, finite float speed (≤500 km/h) or None."""
    if isinstance(value, NUMERIC_TYPES):
        f = float(value)  # type: ignore[arg-type]
        if _isfinite(f) and 0 < f <= 500:
            return f
    return None


def _parse_stale_timeout(value: object) -> float:
    """Return a stale-timeout value clamped to [3, 120], default 10."""
    if isinstance(value, NUMERIC_TYPES):
        return max(3.0, min(120.0, float(value)))  # type: ignore[arg-type]
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


def _coerce_speed_source(value: object) -> SpeedSourceKind:
    if isinstance(value, str):
        try:
            return SpeedSourceKind(value)
        except ValueError:
            pass
    return SpeedSourceKind.GPS


def _coerce_fallback_mode(value: object) -> FallbackMode:
    return "manual"


def new_car_id() -> str:
    """Generate a new unique car configuration ID."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# CarConfig
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CarConfig:
    """Persisted vehicle profile (ID, name, type, geometry aspects, variant)."""

    id: str
    name: str
    car_type: str
    aspects: dict[str, float]
    variant: str | None

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
            car_type=car_type,
            aspects=aspects,
            variant=variant or None,
        )

    def to_dict(self) -> CarConfigPayload:
        """Serialise this car config to a plain dict for JSON persistence."""
        d: CarConfigPayload = {
            "id": self.id,
            "name": self.name,
            "type": self.car_type,
            "aspects": dict(self.aspects),
        }
        if self.variant:
            d["variant"] = self.variant
        return d

    def to_car(self) -> Car:
        """Return the domain ``Car`` value object for this config."""
        from vibesensor.domain import Car

        return Car(
            id=self.id,
            name=self.name,
            car_type=self.car_type,
            aspects=dict(self.aspects),
            variant=self.variant,
        )


# ---------------------------------------------------------------------------
# SensorConfig
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SensorConfig:
    """Persisted configuration for a sensor node (ID, name, location_code)."""

    sensor_id: str
    name: str
    location_code: str

    @classmethod
    def from_dict(cls, sensor_id: str, data: Mapping[str, object]) -> SensorConfig:
        """Construct a :class:`SensorConfig` from *sensor_id* and a raw dict."""
        name = str(data.get("name") or sensor_id).strip()[:64]
        location_code = str(data.get("location_code") or "").strip()[:64]
        return cls(
            sensor_id=sensor_id,
            name=name or sensor_id,
            location_code=location_code,
        )

    def to_dict(self) -> SensorConfigPayload:
        """Serialise this sensor config to a plain dict."""
        return {"name": self.name, "location_code": self.location_code}

    def to_sensor(self) -> Sensor:
        """Return the domain ``Sensor`` value object for this config."""
        from vibesensor.domain import Sensor, SensorPlacement

        placement = SensorPlacement.from_code(self.location_code) if self.location_code else None
        return Sensor(
            sensor_id=self.sensor_id,
            name=self.name,
            placement=placement,
        )


# ---------------------------------------------------------------------------
# SpeedSourceConfig
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
            speed_source=SpeedSourceKind.GPS,
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
        # Validate cross-field invariant early instead of deferring to to_speed_source().
        if self.speed_source == SpeedSourceKind.MANUAL and self.manual_speed_kph is None:
            raise ValueError("SpeedSourceConfig with speed_source=MANUAL requires manual_speed_kph")

    def to_speed_source(self) -> SpeedSource:
        """Return the domain ``SpeedSource`` value object for this config."""
        from vibesensor.domain import SpeedSource

        return SpeedSource(
            kind=self.speed_source,
            manual_speed_kmh=self.manual_speed_kph,
        )


# ---------------------------------------------------------------------------
# RunMetadata
# ---------------------------------------------------------------------------

FFT_WINDOW_TYPE: str = "hann"
PEAK_PICKER_METHOD: str = "canonical_strength_metrics_module"


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
    incomplete_for_order_analysis: bool

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
        accel_scale_g_per_lsb: float | None,
        firmware_version: str | None = None,
        end_time_utc: str | None = None,
        incomplete_for_order_analysis: bool = False,
    ) -> RunMetadata:
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
            fft_window_type=FFT_WINDOW_TYPE,
            peak_picker_method=PEAK_PICKER_METHOD,
            accel_scale_g_per_lsb=accel_scale_g_per_lsb,
            incomplete_for_order_analysis=bool(incomplete_for_order_analysis),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunMetadata:
        from vibesensor.shared.utils.json_utils import as_float_or_none, as_int_or_none

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
            accel_scale_g_per_lsb=as_float_or_none(data.get("accel_scale_g_per_lsb")),
            incomplete_for_order_analysis=bool(data.get("incomplete_for_order_analysis", False)),
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
            "incomplete_for_order_analysis": self.incomplete_for_order_analysis,
        }
