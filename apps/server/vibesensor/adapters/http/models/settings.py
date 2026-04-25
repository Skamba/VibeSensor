"""Settings and analysis-configuration HTTP API models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    LanguageCode,
    SpeedUnitCode,
)
from vibesensor.shared.types.speed_source_config import ResolvedSpeedSource

from .base import _FrozenBase


class AnalysisSettingsRequest(_FrozenBase):
    """Request body for updating vehicle analysis settings (tire geometry, gear ratios, etc.)."""

    tire_width_mm: float | None = Field(default=None, gt=0)
    tire_aspect_pct: float | None = Field(default=None, gt=0)
    rim_in: float | None = Field(default=None, gt=0)
    final_drive_ratio: float | None = Field(default=None, gt=0)
    current_gear_ratio: float | None = Field(default=None, gt=0)
    wheel_bandwidth_pct: float | None = Field(default=None, gt=0)
    driveshaft_bandwidth_pct: float | None = Field(default=None, gt=0)
    engine_bandwidth_pct: float | None = Field(default=None, gt=0)
    speed_uncertainty_pct: float | None = Field(default=None, ge=0)
    tire_diameter_uncertainty_pct: float | None = Field(default=None, ge=0)
    final_drive_uncertainty_pct: float | None = Field(default=None, ge=0)
    gear_uncertainty_pct: float | None = Field(default=None, ge=0)
    min_abs_band_hz: float | None = Field(default=None, ge=0)
    max_band_half_width_pct: float | None = Field(default=None, gt=0)
    tire_deflection_factor: float | None = Field(default=None, ge=0.85, le=1.0)


class LanguageRequest(_FrozenBase):
    """Request body for changing the UI language."""

    language: LanguageCode


class SpeedUnitRequest(_FrozenBase):
    """Request body for changing the displayed speed unit."""

    speed_unit: SpeedUnitCode


class CarUpsertRequest(_FrozenBase):
    """Request body for creating or updating a car profile."""

    name: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    type: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    aspects: AnalysisSettingsPayload | None = None
    variant: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    order_reference_status: CarOrderReferenceStatus | None = None


class CarOrderReferenceStatus(BaseModel):
    """Confidence metadata for saved drivetrain order-reference values."""

    selection_source_status: Literal["compat_projection", "exact_row", "manual_entry"]
    final_drive_ratio_confidence: str | None = None
    current_gear_ratio_confidence: str | None = None
    transmission_name: str | None = None
    transmission_confidence: str | None = None
    requires_manual_confirmation: bool


class ActiveCarRequest(_FrozenBase):
    """Request body for selecting the active car profile."""

    car_id: str = Field(min_length=1)


class SpeedSourceRequest(_FrozenBase):
    """Request body for configuring the speed source (GPS, manual, OBD2, etc.)."""

    speed_source: SpeedSourceKind | None = None
    manual_speed_kph: float | None = Field(default=None, ge=0, le=500)
    stale_timeout_s: float | None = Field(default=None, ge=3, le=120)
    obd_device_mac: str | None = Field(default=None, min_length=1, max_length=64)
    obd_device_name: str | None = Field(default=None, min_length=1, max_length=128)


class CarResponse(BaseModel):
    """Response body representing a single car profile."""

    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: str | None = None
    order_reference_status: CarOrderReferenceStatus | None = None


class CarsResponse(BaseModel):
    """Response body for the list of all car profiles with the active car ID."""

    cars: list[CarResponse]
    active_car_id: str | None


class SpeedSourceResponse(BaseModel):
    """Response body for the current speed-source configuration."""

    speed_source: SpeedSourceKind
    manual_speed_kph: float | None
    stale_timeout_s: float
    obd_device_mac: str | None = None
    obd_device_name: str | None = None


class SpeedSourceStatusResponse(BaseModel):
    """Response body for the live GPS/speed-source connection status."""

    gps_enabled: bool
    connection_state: str
    device: str | None
    fix_mode: int | None
    fix_dimension: Literal["3d", "2d", "none"]
    speed_confidence: Literal["low", "medium", "high"]
    epx_m: float | None
    epy_m: float | None
    epv_m: float | None
    last_update_age_s: float | None
    raw_speed_kmh: float | None
    effective_speed_kmh: float | None
    last_error: str | None
    reconnect_delay_s: float | None
    fallback_active: bool
    speed_source: ResolvedSpeedSource
    stale_timeout_s: float


class ObdPairRequest(_FrozenBase):
    """Request body for pairing and selecting a Bluetooth OBD adapter."""

    mac_address: str = Field(min_length=1, max_length=64)


class ObdDeviceResponse(BaseModel):
    """Single discovered or configured Bluetooth OBD adapter."""

    mac_address: str
    name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None


class ObdScanResponse(BaseModel):
    """Response body for a Bluetooth OBD discovery scan."""

    devices: list[ObdDeviceResponse]


class ObdPairResponse(BaseModel):
    """Response body after pairing and persisting a Bluetooth OBD adapter."""

    configured_device_mac: str
    configured_device_name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None


class ObdStatusResponse(BaseModel):
    """Detailed Bluetooth OBD runtime status for diagnostics and field recovery."""

    configured_device_mac: str | None
    configured_device_name: str | None
    connection_state: str
    device_mac: str | None
    device_name: str | None
    paired: bool
    trusted: bool
    connected: bool
    rfcomm_channel: int | None
    last_sample_age_s: float | None
    last_speed_kmh: float | None
    last_rpm: float | None
    rpm_sample_age_s: float | None
    rpm_target_interval_ms: int | None
    rpm_effective_hz: float | None
    request_rtt_ms: float | None
    timeout_count: int
    error_count: int
    poll_mode: str | None
    backoff_active: bool
    last_error: str | None
    last_raw_response: str | None
    reconnect_delay_s: float | None
    debug_hint: str | None


class LanguageResponse(BaseModel):
    """Response body confirming the active UI language."""

    language: str


class SpeedUnitResponse(BaseModel):
    """Response body confirming the active speed unit."""

    speed_unit: SpeedUnitCode


class AnalysisSettingsResponse(BaseModel):
    """Response body reflecting the current validated analysis settings."""

    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float
    final_drive_ratio: float
    current_gear_ratio: float
    wheel_bandwidth_pct: float
    driveshaft_bandwidth_pct: float
    engine_bandwidth_pct: float
    speed_uncertainty_pct: float
    tire_diameter_uncertainty_pct: float
    final_drive_uncertainty_pct: float
    gear_uncertainty_pct: float
    min_abs_band_hz: float
    max_band_half_width_pct: float
    tire_deflection_factor: float
