"""Pydantic models for the live WebSocket payload contract.

These models define the versioned schema for server→UI real-time messages.
The ``schema_version`` field lets frontend and backend evolve independently
while catching drift in CI via the exported JSON Schema artifact.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from vibesensor_core.vibration_strength import StrengthPeak

from .payload_types import (
    TimingHealthPayload,
)

# Bump this when the payload shape changes in a backwards-incompatible way.
SCHEMA_VERSION: str = "1"

__all__ = [
    "SCHEMA_VERSION",
    "AlignmentInfo",
    "ClientInfoModel",
    "FrequencyWarning",
    "LiveWsPayload",
    "OrderBand",
    "RotationalSpeedValue",
    "RotationalSpeeds",
    "SpectraPayload",
    "SpectrumPeak",
    "SpectrumSeries",
    "StrengthMetricsModel",
]


class SpectrumPeak(BaseModel):
    """A single spectral peak identified in the signal."""

    model_config = ConfigDict(extra="allow", frozen=True)

    hz: float
    amp: float


class StrengthMetricsModel(BaseModel):
    """Structured vibration-strength metrics with explicit defaults."""

    model_config = ConfigDict(extra="forbid")

    combined_spectrum_amp_g: list[float] = Field(default_factory=list)
    vibration_strength_db: float = 0.0
    peak_amp_g: float = 0.0
    noise_floor_amp_g: float = 0.0
    strength_bucket: str | None = None
    top_peaks: list[StrengthPeak] = Field(default_factory=list)


class SpectrumSeries(BaseModel):
    """Per-client spectrum data sent on heavy ticks."""

    model_config = ConfigDict(extra="allow")

    x: list[float] = []
    y: list[float] = []
    z: list[float] = []
    combined_spectrum_amp_g: list[float] = []
    strength_metrics: StrengthMetricsModel = Field(default_factory=StrengthMetricsModel)
    freq: list[float] | None = None


class ClientInfoModel(BaseModel):
    """Structured client row with explicit defaults for optional construction."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    mac_address: str = ""
    name: str = ""
    connected: bool = False
    location: str = ""
    firmware_version: str = ""
    sample_rate_hz: int = 0
    frame_samples: int = 0
    last_seen_age_ms: int | None = None
    data_addr: tuple[str, int] | None = None
    control_addr: tuple[str, int] | None = None
    frames_total: int = 0
    dropped_frames: int = 0
    duplicates_received: int = 0
    queue_overflow_drops: int = 0
    parse_errors: int = 0
    server_queue_drops: int = 0
    latest_metrics: dict[str, object] = Field(default_factory=dict)
    last_ack_cmd_seq: int | None = None
    last_ack_status: int | None = None
    reset_count: int = 0
    last_reset_time: float | None = None
    timing_health: TimingHealthPayload = Field(
        default_factory=lambda: {"jitter_us_ema": 0.0, "drift_us_total": 0.0},
    )


class AlignmentInfo(BaseModel):
    """Multi-sensor clock-alignment quality metrics for a frequency window."""

    model_config = ConfigDict(frozen=True)
    overlap_ratio: float
    aligned: bool
    shared_window_s: float
    sensor_count: int
    clock_synced: bool


class FrequencyWarning(BaseModel):
    """Warning about frequency data quality issues in a spectra payload."""

    model_config = ConfigDict(frozen=True)
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
    """Current rotational speed estimate with source and confidence metadata."""

    model_config = ConfigDict(frozen=True)
    rpm: float | None = None
    mode: str | None = None
    reason: str | None = None


class OrderBand(BaseModel):
    """Frequency band for a specific rotation-order harmonic."""

    model_config = ConfigDict(frozen=True)
    key: str
    center_hz: float
    tolerance: float


class RotationalSpeeds(BaseModel):
    """Current per-system rotational speed estimates (wheel, driveshaft, engine)."""

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
    clients: list[ClientInfoModel] = []
    selected_client_id: str | None = None
    rotational_speeds: RotationalSpeeds | None = None
    spectra: SpectraPayload | None = None
