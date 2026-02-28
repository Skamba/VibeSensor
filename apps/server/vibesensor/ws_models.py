"""Pydantic models for the live WebSocket payload contract.

These models define the versioned schema for server→UI real-time messages.
The ``schema_version`` field lets frontend and backend evolve independently
while catching drift in CI via the exported JSON Schema artifact.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# Bump this when the payload shape changes in a backwards-incompatible way.
SCHEMA_VERSION: str = "1"


class SpectrumPeak(BaseModel):
    """A single spectral peak identified in the signal."""

    model_config = ConfigDict(extra="allow")

    hz: float
    amp: float


class SpectrumSeries(BaseModel):
    """Per-client spectrum data sent on heavy ticks."""

    model_config = ConfigDict(extra="allow")

    x: list[float] = []
    y: list[float] = []
    z: list[float] = []
    combined_spectrum_amp_g: list[float] = []
    strength_metrics: dict[str, Any] = {}
    freq: list[float] | None = None


class AlignmentInfo(BaseModel):
    overlap_ratio: float
    aligned: bool
    shared_window_s: float
    sensor_count: int
    clock_synced: bool


class FrequencyWarning(BaseModel):
    code: str
    message: str
    client_ids: list[str]


class SpectraPayload(BaseModel):
    """Top-level spectra block included on heavy ticks."""

    model_config = ConfigDict(extra="allow")

    freq: list[float] = []
    clients: dict[str, SpectrumSeries] = {}
    alignment: AlignmentInfo | None = None
    warning: FrequencyWarning | None = None


class RotationalSpeedValue(BaseModel):
    rpm: float | None = None
    mode: str | None = None
    reason: str | None = None


class OrderBand(BaseModel):
    key: str
    center_hz: float
    tolerance: float


class RotationalSpeeds(BaseModel):
    basis_speed_source: str | None = None
    wheel: RotationalSpeedValue = RotationalSpeedValue()
    driveshaft: RotationalSpeedValue = RotationalSpeedValue()
    engine: RotationalSpeedValue = RotationalSpeedValue()
    order_bands: list[OrderBand] | None = None


class LiveWsPayload(BaseModel):
    """Root model for every WebSocket message pushed to the UI."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    server_time: str
    speed_mps: float | None = None
    clients: list[dict[str, Any]] = []
    selected_client_id: str | None = None
    rotational_speeds: RotationalSpeeds | None = None
    spectra: SpectraPayload | None = None
    diagnostics: dict[str, Any] = {}
