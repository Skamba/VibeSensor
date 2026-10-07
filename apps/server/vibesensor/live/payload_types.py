from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

import numpy as np
import numpy.typing as npt

from vibesensor.domain.sensor_firmware import FirmwareStatus
from vibesensor.dsp.vibration_strength import StrengthPeak, VibrationStrengthMetrics

# Bump this when the payload shape changes in a backwards-incompatible way.
SCHEMA_VERSION: str = "1"


class IntakeStatsPayload(TypedDict):
    total_ingested_samples: int
    total_compute_calls: int
    last_compute_duration_s: float
    last_compute_all_duration_s: float
    last_ingest_duration_s: float


class AxisPeak(TypedDict, total=False):
    hz: float
    amp: float
    snr_ratio: float


class AxisMetrics(TypedDict):
    """One axis's amplitude spectrum (g) on its frequency bins (Hz)."""

    freq: npt.NDArray[np.float32]
    amp: npt.NDArray[np.float32]


class CombinedMetrics(TypedDict, total=False):
    peaks: list[StrengthPeak]
    strength_metrics: VibrationStrengthMetrics


class ClientMetrics(TypedDict, total=False):
    x: AxisMetrics
    y: AxisMetrics
    z: AxisMetrics
    combined: CombinedMetrics


class ClientApiRow(TypedDict, total=True):
    id: str
    mac_address: str
    name: str
    connected: bool
    location_code: str
    firmware_version: str
    firmware_status: FirmwareStatus
    """The reported firmware against the firmware this Pi would flash."""
    sample_rate_hz: int
    last_seen_age_ms: int | None
    frames_total: int
    dropped_frames: int
    """Frames lost since the sensor was first seen (diagnostics; never resets)."""
    frame_loss_recent: bool
    """The sensor lost a significant share of its frames in the last minute."""
    frame_samples: int


class SpectrumSeriesPayload(TypedDict, total=False):
    combined_spectrum_amp_g: list[float]
    strength_metrics: VibrationStrengthMetrics
    freq: list[float]


class SpectraPayload(TypedDict, total=False):
    frame_fingerprint: str
    freq: list[float]
    clients: dict[str, SpectrumSeriesPayload]


WsErrorCode = Literal["payload_build_failed"]


class WsErrorPayload(TypedDict):
    error: WsErrorCode


class WsClientSelectionPayload(TypedDict, total=False):
    client_id: str | None


class RotationalSpeedValuePayload(TypedDict):
    rpm: float | None
    mode: str | None
    reason: str | None


class OrderBandPayload(TypedDict):
    key: str
    center_hz: float
    tolerance: float
    # The engine's firing order (E3 for a six); absent on every other band.
    firing: NotRequired[bool]


class RotationalSpeedsPayload(TypedDict):
    basis_speed_source: str | None
    wheel: RotationalSpeedValuePayload
    driveshaft: RotationalSpeedValuePayload
    engine: RotationalSpeedValuePayload
    order_bands: list[OrderBandPayload] | None


class LiveWsPayload(TypedDict):
    schema_version: str
    server_time: str
    speed_mps: float | None
    clients: list[ClientApiRow]
    selected_client_id: str | None
    rotational_speeds: RotationalSpeedsPayload | None
    spectra: NotRequired[SpectraPayload]
