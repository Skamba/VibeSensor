"""Pydantic request/response models for the VibeSensor HTTP API.

Separated from ``api.py`` to keep routing logic distinct from data contracts.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    # Request models
    "IdentifyRequest",
    "SetLocationRequest",
    "AnalysisSettingsRequest",
    "LanguageRequest",
    "SpeedUnitRequest",
    "CarUpsertRequest",
    "ActiveCarRequest",
    "SpeedSourceRequest",
    "UpdateStartRequest",
    "EspFlashStartRequest",
    "SensorRequest",
    # Response models
    "HealthResponse",
    "CarResponse",
    "CarsResponse",
    "SpeedSourceResponse",
    "SpeedSourceStatusResponse",
    "SensorConfigResponse",
    "SensorsResponse",
    "LanguageResponse",
    "SpeedUnitResponse",
    "ClientsResponse",
    "LocationOptionResponse",
    "ClientLocationsResponse",
    "AnalysisSettingsResponse",
    "IdentifyResponse",
    "SetClientLocationResponse",
    "RemoveClientResponse",
    "LoggingStatusResponse",
    "HistoryListResponse",
    "HistoryRunResponse",
    "HistoryInsightsResponse",
    "DeleteHistoryRunResponse",
    "UpdateIssueResponse",
    "UpdateStatusResponse",
    "UpdateStartResponse",
    "UpdateCancelResponse",
    "EspSerialPortResponse",
    "EspFlashPortsResponse",
    "EspFlashStatusResponse",
    "EspFlashStartResponse",
    "EspFlashCancelResponse",
    "EspFlashLogsResponse",
    "EspFlashHistoryEntryResponse",
    "EspFlashHistoryResponse",
    "CarLibraryBrandsResponse",
    "CarLibraryTypesResponse",
    "CarLibraryGearboxEntry",
    "CarLibraryTireOptionEntry",
    "CarLibraryVariantEntry",
    "CarLibraryModelEntry",
    "CarLibraryModelsResponse",
]

# ---------------------------------------------------------------------------
# Shared base classes
# ---------------------------------------------------------------------------


class _FrozenBase(BaseModel):
    """Immutable base for request models (constructed once, never mutated)."""

    model_config = ConfigDict(frozen=True)


class _ExtraAllowBase(BaseModel):
    """Base for models that accept arbitrary extra fields."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class IdentifyRequest(_FrozenBase):
    """Request body for the ``/api/clients/{id}/identify`` endpoint."""

    duration_ms: int = Field(default=1500, ge=100, le=60_000)


class SetLocationRequest(_FrozenBase):
    """Request body for setting the sensor location code."""

    location_code: str = Field(min_length=0, max_length=64)


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


class LanguageRequest(_FrozenBase):
    """Request body for changing the UI language."""

    language: str = Field(pattern="^(en|nl)$")


class SpeedUnitRequest(_FrozenBase):
    """Request body for changing the displayed speed unit."""

    speedUnit: str = Field(pattern="^(kmh|mps)$")


class CarUpsertRequest(_FrozenBase):
    """Request body for creating or updating a car profile."""

    name: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    type: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    aspects: dict[str, float] | None = None
    variant: Annotated[str, Field(min_length=1, max_length=64)] | None = None


class ActiveCarRequest(_FrozenBase):
    """Request body for selecting the active car profile."""

    carId: str = Field(min_length=1)


class SpeedSourceRequest(_FrozenBase):
    """Request body for configuring the speed source (GPS, manual, OBD2, etc.)."""

    speedSource: str | None = None
    manualSpeedKph: float | None = Field(default=None, ge=0, le=500)
    staleTimeoutS: float | None = Field(default=None, ge=1, le=300)
    fallbackMode: str | None = None


class UpdateStartRequest(_FrozenBase):
    """Request body to start an OTA software update (provides Wi-Fi credentials)."""

    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)


class EspFlashStartRequest(_FrozenBase):
    """Request body to start an ESP32 firmware flash job."""

    port: str | None = None
    auto_detect: bool = True


class SensorRequest(_FrozenBase):
    """Request body for updating sensor name and location."""

    name: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response body for the server health check endpoint."""

    status: str
    processing_state: str
    processing_failures: int
    intake_stats: dict[str, Any] = Field(default_factory=dict)


class CarResponse(BaseModel):
    """Response body representing a single car profile."""

    id: str
    name: str
    type: str
    aspects: dict[str, float]
    variant: str | None = None


class CarsResponse(BaseModel):
    """Response body for the list of all car profiles with the active car ID."""

    cars: list[CarResponse]
    activeCarId: str | None


class SpeedSourceResponse(BaseModel):
    """Response body for the current speed-source configuration."""

    speedSource: str
    manualSpeedKph: float | None = None
    obd2Config: dict[str, Any] = Field(default_factory=dict)
    staleTimeoutS: float
    fallbackMode: str


class SpeedSourceStatusResponse(BaseModel):
    """Response body for the live GPS/speed-source connection status."""

    gps_enabled: bool
    connection_state: str
    device: str | None = None
    fix_mode: int | None = None
    fix_dimension: str | None = None
    speed_confidence: str | None = None
    epx_m: float | None = None
    epy_m: float | None = None
    epv_m: float | None = None
    last_update_age_s: float | None = None
    raw_speed_kmh: float | None = None
    effective_speed_kmh: float | None = None
    last_error: str | None = None
    reconnect_delay_s: float | None = None
    fallback_active: bool
    stale_timeout_s: float
    fallback_mode: str


class SensorConfigResponse(BaseModel):
    """Response body with persisted config for a single sensor (name, location)."""

    name: str
    location: str


class SensorsResponse(BaseModel):
    """Response body mapping MAC addresses to sensor config responses."""

    sensorsByMac: dict[str, SensorConfigResponse]


class LanguageResponse(BaseModel):
    """Response body confirming the active UI language."""

    language: str


class SpeedUnitResponse(BaseModel):
    """Response body confirming the active speed unit."""

    speedUnit: str


class ClientsResponse(BaseModel):
    """Response body listing all currently-connected sensor clients."""

    clients: list[dict[str, Any]]


class LocationOptionResponse(BaseModel):
    """A single sensor-location option (code + human-readable label)."""

    code: str
    label: str


class ClientLocationsResponse(BaseModel):
    """Response body with available sensor-location options."""

    locations: list[LocationOptionResponse]


class AnalysisSettingsResponse(_ExtraAllowBase):
    """Response body reflecting the current analysis settings (all fields pass-through)."""

    pass


class IdentifyResponse(BaseModel):
    """Response body for a sensor identify (blink) command."""

    status: str
    cmd_seq: int | None = None


class SetClientLocationResponse(BaseModel):
    """Response body confirming the new location assignment for a client."""

    id: str
    mac_address: str
    location_code: str
    name: str


class RemoveClientResponse(BaseModel):
    """Response body confirming removal of a disconnected client."""

    id: str
    status: str


class LoggingStatusResponse(BaseModel):
    """Response body with the current recording (run-logging) status."""

    enabled: bool
    current_file: str | None = None
    run_id: str | None = None
    write_error: str | None = None
    analysis_in_progress: bool


class HistoryListResponse(BaseModel):
    """Response body listing recorded run summaries."""

    runs: list[dict[str, Any]]


class HistoryRunResponse(_ExtraAllowBase):
    """Response body for a single history run with metadata and optional analysis."""

    run_id: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] | None = None


class HistoryInsightsResponse(_ExtraAllowBase):
    """Response body with aggregated diagnostic insights for a run."""

    run_id: str | None = None
    status: str | None = None


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str


class UpdateIssueResponse(BaseModel):
    """Response body for a single issue raised during an OTA update phase."""

    phase: str
    message: str
    detail: str


class UpdateStatusResponse(BaseModel):
    """Response body for the full OTA update job status."""

    state: str
    phase: str
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    ssid: str
    issues: list[UpdateIssueResponse]
    log_tail: list[str]
    exit_code: int | None = None
    runtime: dict[str, Any] = Field(default_factory=dict)


class UpdateStartResponse(BaseModel):
    """Response body confirming that an OTA update job has started."""

    status: str
    ssid: str


class UpdateCancelResponse(BaseModel):
    """Response body confirming whether an OTA update job was cancelled."""

    cancelled: bool


class EspSerialPortResponse(BaseModel):
    """Response body describing a single detected serial port."""

    port: str
    description: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None


class EspFlashPortsResponse(BaseModel):
    """Response body listing detected serial ports for ESP32 flashing."""

    ports: list[EspSerialPortResponse]


class EspFlashStatusResponse(BaseModel):
    """Response body for the current ESP32 flash job status."""

    state: str
    phase: str
    job_id: int | None = None
    selected_port: str | None = None
    auto_detect: bool
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    exit_code: int | None = None
    error: str | None = None
    log_count: int


class EspFlashStartResponse(BaseModel):
    """Response body confirming that an ESP32 flash job has been queued."""

    status: str
    job_id: int


class EspFlashCancelResponse(BaseModel):
    """Response body confirming whether an ESP32 flash job was cancelled."""

    cancelled: bool


class EspFlashLogsResponse(BaseModel):
    """Response body with a page of ESP32 flash log lines."""

    from_index: int
    next_index: int
    lines: list[str]


class EspFlashHistoryEntryResponse(BaseModel):
    """Response body for a single historical ESP32 flash job."""

    job_id: int
    state: str
    selected_port: str | None = None
    auto_detect: bool
    started_at: float
    finished_at: float | None = None
    exit_code: int | None = None
    error: str | None = None


class EspFlashHistoryResponse(BaseModel):
    """Response body listing all past ESP32 flash job attempts."""

    attempts: list[EspFlashHistoryEntryResponse]


class CarLibraryBrandsResponse(BaseModel):
    """Response body listing available car manufacturer brands."""

    brands: list[str]


class CarLibraryTypesResponse(BaseModel):
    """Response body listing available car body types."""

    types: list[str]


class CarLibraryGearboxEntry(_ExtraAllowBase):
    """A gearbox option from the car library (gear ratios)."""

    name: str
    final_drive_ratio: float = Field(gt=0)
    top_gear_ratio: float = Field(gt=0)


class CarLibraryTireOptionEntry(_ExtraAllowBase):
    """A tire size option from the car library."""

    name: str
    tire_width_mm: float = Field(gt=0)
    tire_aspect_pct: float = Field(gt=0)
    rim_in: float = Field(gt=0)


class CarLibraryVariantEntry(_ExtraAllowBase):
    """A specific variant/trim of a car library model entry."""

    name: str
    engine: str | None = None
    drivetrain: str
    gearboxes: list[CarLibraryGearboxEntry] | None = None
    tire_options: list[CarLibraryTireOptionEntry] | None = None
    tire_width_mm: float | None = None
    tire_aspect_pct: float | None = None
    rim_in: float | None = None


class CarLibraryModelEntry(_ExtraAllowBase):
    """A full car library entry with brand, model, tire options, and variants."""

    brand: str
    type: str
    model: str
    gearboxes: list[CarLibraryGearboxEntry]
    tire_options: list[CarLibraryTireOptionEntry]
    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float
    variants: list[CarLibraryVariantEntry]


class CarLibraryModelsResponse(BaseModel):
    """Response body listing car library model entries."""

    models: list[CarLibraryModelEntry]
