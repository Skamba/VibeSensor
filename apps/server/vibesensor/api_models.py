"""Pydantic request/response models for the VibeSensor HTTP API.

Separated from ``api.py`` to keep routing logic distinct from data contracts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class IdentifyRequest(BaseModel):
    duration_ms: int = Field(default=1500, ge=100, le=60_000)


class SetLocationRequest(BaseModel):
    location_code: str = Field(min_length=0, max_length=64)


class AnalysisSettingsRequest(BaseModel):
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


class LanguageRequest(BaseModel):
    language: str = Field(pattern="^(en|nl)$")


class SpeedUnitRequest(BaseModel):
    speedUnit: str = Field(pattern="^(kmh|mps)$")


class CarUpsertRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    aspects: dict[str, float] | None = None
    variant: str | None = None


class ActiveCarRequest(BaseModel):
    carId: str = Field(min_length=1)


class SpeedSourceRequest(BaseModel):
    speedSource: str | None = None
    manualSpeedKph: float | None = None
    staleTimeoutS: float | None = None
    fallbackMode: str | None = None


class UpdateStartRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)


class EspFlashStartRequest(BaseModel):
    port: str | None = None
    auto_detect: bool = True


class SensorRequest(BaseModel):
    name: str | None = None
    location: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    processing_state: str
    processing_failures: int


class CarResponse(BaseModel):
    id: str
    name: str
    type: str
    aspects: dict[str, float]
    variant: str | None = None


class CarsResponse(BaseModel):
    cars: list[CarResponse]
    activeCarId: str | None


class SpeedSourceResponse(BaseModel):
    speedSource: str
    manualSpeedKph: float | None = None
    obd2Config: dict[str, Any] = Field(default_factory=dict)
    staleTimeoutS: float
    fallbackMode: str


class SpeedSourceStatusResponse(BaseModel):
    gps_enabled: bool
    connection_state: str
    device: str | None = None
    last_update_age_s: float | None = None
    raw_speed_kmh: float | None = None
    effective_speed_kmh: float | None = None
    last_error: str | None = None
    reconnect_delay_s: float | None = None
    fallback_active: bool
    stale_timeout_s: float
    fallback_mode: str


class SensorConfigResponse(BaseModel):
    name: str
    location: str


class SensorsResponse(BaseModel):
    sensorsByMac: dict[str, SensorConfigResponse]


class LanguageResponse(BaseModel):
    language: str


class SpeedUnitResponse(BaseModel):
    speedUnit: str


class ClientsResponse(BaseModel):
    clients: list[dict[str, Any]]


class LocationOptionResponse(BaseModel):
    code: str
    label: str


class ClientLocationsResponse(BaseModel):
    locations: list[LocationOptionResponse]


class AnalysisSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class IdentifyResponse(BaseModel):
    status: str
    cmd_seq: int | None = None


class SetClientLocationResponse(BaseModel):
    id: str
    mac_address: str
    location_code: str
    name: str


class RemoveClientResponse(BaseModel):
    id: str
    status: str


class LoggingStatusResponse(BaseModel):
    enabled: bool
    current_file: str | None = None
    run_id: str | None = None
    write_error: str | None = None
    analysis_in_progress: bool


class HistoryListResponse(BaseModel):
    runs: list[dict[str, Any]]


class HistoryRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] | None = None


class HistoryInsightsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str | None = None
    status: str | None = None


class DeleteHistoryRunResponse(BaseModel):
    run_id: str
    status: str


class UpdateIssueResponse(BaseModel):
    phase: str
    message: str
    detail: str


class UpdateStatusResponse(BaseModel):
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
    status: str
    ssid: str


class UpdateCancelResponse(BaseModel):
    cancelled: bool


class EspSerialPortResponse(BaseModel):
    port: str
    description: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None


class EspFlashPortsResponse(BaseModel):
    ports: list[EspSerialPortResponse]


class EspFlashStatusResponse(BaseModel):
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
    status: str
    job_id: int


class EspFlashCancelResponse(BaseModel):
    cancelled: bool


class EspFlashLogsResponse(BaseModel):
    from_index: int
    next_index: int
    lines: list[str]


class EspFlashHistoryEntryResponse(BaseModel):
    job_id: int
    state: str
    selected_port: str | None = None
    auto_detect: bool
    started_at: float
    finished_at: float | None = None
    exit_code: int | None = None
    error: str | None = None


class EspFlashHistoryResponse(BaseModel):
    attempts: list[EspFlashHistoryEntryResponse]


class CarLibraryBrandsResponse(BaseModel):
    brands: list[str]


class CarLibraryTypesResponse(BaseModel):
    types: list[str]


class CarLibraryGearboxEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    final_drive_ratio: float
    top_gear_ratio: float


class CarLibraryTireOptionEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float


class CarLibraryVariantEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    engine: str | None = None
    drivetrain: str
    gearboxes: list[CarLibraryGearboxEntry] | None = None
    tire_options: list[CarLibraryTireOptionEntry] | None = None
    tire_width_mm: float | None = None
    tire_aspect_pct: float | None = None
    rim_in: float | None = None


class CarLibraryModelEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
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
    models: list[CarLibraryModelEntry]
