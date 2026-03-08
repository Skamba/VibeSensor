"""Pydantic request/response models for the VibeSensor HTTP API.

Separated from ``api.py`` to keep routing logic distinct from data contracts.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    "HealthDataLossResponse",
    "HealthIntakeStatsResponse",
    "HealthPersistenceResponse",
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
    "HistoryListEntryResponse",
    "HistoryListResponse",
    "HistoryRunResponse",
    "HistoryInsightWarningResponse",
    "HistoryInsightsResponse",
    "DeleteHistoryRunResponse",
    "UpdateRuntimeResponse",
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
    tire_deflection_factor: float | None = Field(default=None, ge=0.85, le=1.0)


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

    speedSource: Literal["gps", "obd2", "manual"] | None = None
    manualSpeedKph: float | None = Field(default=None, ge=0, le=500)
    staleTimeoutS: float | None = Field(default=None, ge=3, le=120)
    fallbackMode: Literal["manual"] | None = None


class UpdateStartRequest(_FrozenBase):
    """Request body to start an OTA software update (provides Wi-Fi credentials)."""

    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)


class EspFlashStartRequest(_FrozenBase):
    """Request body to start an ESP32 firmware flash job."""

    port: str | None = None
    auto_detect: bool = True

    @model_validator(mode="after")
    def _require_port_when_not_auto_detect(self) -> EspFlashStartRequest:
        """When auto_detect is False a port must be provided explicitly."""
        if not self.auto_detect and not self.port:
            raise ValueError("port is required when auto_detect is False")
        return self


class SensorRequest(_FrozenBase):
    """Request body for updating sensor name and location."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    location: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HealthDataLossResponse(BaseModel):
    """Response body for aggregated client data-loss counters."""

    tracked_clients: int
    affected_clients: int
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int


class HealthPersistenceResponse(BaseModel):
    """Response body for persistence health details."""

    write_error: str | None
    analysis_in_progress: bool
    analysis_queue_depth: int = 0
    analysis_queue_max_depth: int = 0
    analysis_active_run_id: str | None = None
    analysis_started_at: float | None = None
    analysis_elapsed_s: float | None = None
    analysis_queue_oldest_age_s: float | None = None
    analyzing_run_count: int = 0
    analyzing_oldest_age_s: float | None = None


class HealthIntakeStatsResponse(BaseModel):
    """Response body for processing intake timing and throughput counters."""

    total_ingested_samples: int
    total_compute_calls: int
    last_compute_duration_s: float
    last_compute_all_duration_s: float
    last_ingest_duration_s: float


class HealthResponse(BaseModel):
    """Response body for the server health check endpoint."""

    status: Literal["ok", "degraded"]
    startup_state: str
    startup_phase: str
    startup_error: str | None
    background_task_failures: dict[str, str]
    processing_state: str
    processing_failures: int
    processing_failure_categories: dict[str, int]
    processing_last_failure: str | None
    sample_rate_mismatch_count: int
    frame_size_mismatch_count: int

    degradation_reasons: list[str]
    data_loss: HealthDataLossResponse
    persistence: HealthPersistenceResponse
    intake_stats: HealthIntakeStatsResponse


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
    manualSpeedKph: float | None
    obd2Config: dict[str, Any] = Field(default_factory=dict)
    staleTimeoutS: float
    fallbackMode: str


class SpeedSourceStatusResponse(BaseModel):
    """Response body for the live GPS/speed-source connection status."""

    gps_enabled: bool
    connection_state: str
    device: str | None
    fix_mode: int | None
    fix_dimension: str | None
    speed_confidence: str | None
    epx_m: float | None
    epy_m: float | None
    epv_m: float | None
    last_update_age_s: float | None
    raw_speed_kmh: float | None
    effective_speed_kmh: float | None
    last_error: str | None
    reconnect_delay_s: float | None
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
    current_file: str | None
    run_id: str | None
    write_error: str | None
    analysis_in_progress: bool


class HistoryListEntryResponse(BaseModel):
    """Response body for a single history-run list row."""

    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None = None
    created_at: str
    sample_count: int
    error_message: str | None = None
    analysis_version: int | None = None


class HistoryListResponse(BaseModel):
    """Response body listing recorded run summaries."""

    runs: list[HistoryListEntryResponse]


class HistoryRunResponse(_ExtraAllowBase):
    """Response body for a single history run with metadata and optional analysis."""

    run_id: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] | None = None


class HistoryInsightWarningResponse(BaseModel):
    """Response body for a localized history/run trust warning."""

    code: str
    severity: Literal["warn", "error"]
    applies_to: str
    title: str
    detail: str | None = None


class HistoryInsightsResponse(_ExtraAllowBase):
    """Response body with aggregated diagnostic insights for a run."""

    run_id: str | None = None
    status: str | None = None
    analysis_is_current: bool | None = None
    warnings: list[HistoryInsightWarningResponse] = Field(default_factory=list)


class DeleteHistoryRunResponse(BaseModel):
    """Response body confirming deletion of a history run."""

    run_id: str
    status: str


class UpdateIssueResponse(BaseModel):
    """Response body for a single issue raised during an OTA update phase."""

    phase: str
    message: str
    detail: str


class UpdateRuntimeResponse(BaseModel):
    """Response body for updater runtime/build verification details."""

    version: str
    commit: str
    ui_source_hash: str
    static_assets_hash: str
    static_build_source_hash: str
    static_build_commit: str
    assets_verified: bool
    has_packaged_static: bool


class UpdateStatusResponse(BaseModel):
    """Response body for the full OTA update job status."""

    state: str
    phase: str
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    phase_started_at: float | None = None
    phase_elapsed_s: float | None = None
    updated_at: float | None = None
    ssid: str
    issues: list[UpdateIssueResponse]
    log_tail: list[str]
    exit_code: int | None = None
    runtime: UpdateRuntimeResponse


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

    name: str = Field(min_length=1)
    final_drive_ratio: float = Field(gt=0)
    top_gear_ratio: float = Field(gt=0)


class CarLibraryTireOptionEntry(_ExtraAllowBase):
    """A tire size option from the car library."""

    name: str = Field(min_length=1)
    tire_width_mm: float = Field(gt=0)
    tire_aspect_pct: float = Field(gt=0)
    rim_in: float = Field(gt=0)


class CarLibraryVariantEntry(_ExtraAllowBase):
    """A specific variant/trim of a car library model entry."""

    name: str = Field(min_length=1)
    engine: str | None = None
    drivetrain: Literal["FWD", "RWD", "AWD"]
    gearboxes: list[CarLibraryGearboxEntry] | None = None
    tire_options: list[CarLibraryTireOptionEntry] | None = None
    tire_width_mm: float | None = Field(default=None, gt=0)
    tire_aspect_pct: float | None = Field(default=None, gt=0)
    rim_in: float | None = Field(default=None, gt=0)


class CarLibraryModelEntry(_ExtraAllowBase):
    """A full car library entry with brand, model, tire options, and variants."""

    brand: str
    type: str
    model: str
    gearboxes: list[CarLibraryGearboxEntry] = Field(min_length=1)
    tire_options: list[CarLibraryTireOptionEntry] = Field(min_length=1)
    tire_width_mm: float = Field(gt=0)
    tire_aspect_pct: float = Field(gt=0)
    rim_in: float = Field(gt=0)
    variants: list[CarLibraryVariantEntry] = Field(default_factory=list)


class CarLibraryModelsResponse(BaseModel):
    """Response body listing car library model entries."""

    models: list[CarLibraryModelEntry]
