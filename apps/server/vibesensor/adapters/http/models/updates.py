"""Updater and ESP flashing HTTP API models."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from .base import _FrozenBase


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
