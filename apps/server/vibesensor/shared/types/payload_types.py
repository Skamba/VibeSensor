from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from pydantic import ConfigDict

from vibesensor.vibration_strength import StrengthPeak, VibrationStrengthMetrics

# Bump this when the payload shape changes in a backwards-incompatible way.
SCHEMA_VERSION: str = "1"


class WorkerPoolStats(TypedDict):
    max_workers: int
    max_queue_size: int
    max_pending_tasks: int
    total_tasks: int
    pending_tasks: int
    queued_tasks: int
    running_tasks: int
    rejected_tasks: int
    total_run_s: float
    avg_run_s: float
    total_submit_wait_s: float
    avg_submit_wait_s: float
    default_submit_timeout_s: float | None
    alive: bool


class IntakeStatsPayload(TypedDict):
    total_ingested_samples: int
    total_compute_calls: int
    last_compute_duration_s: float
    last_compute_all_duration_s: float
    last_ingest_duration_s: float
    worker_pool: NotRequired[WorkerPoolStats]


class AxisPeak(TypedDict, total=False):
    hz: float
    amp: float
    snr_ratio: float


class AxisMetrics(TypedDict):
    rms: float
    p2p: float
    peaks: list[AxisPeak]


class CombinedMetrics(TypedDict, total=False):
    vib_mag_rms: float
    vib_mag_p2p: float
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
    sample_rate_hz: int
    last_seen_age_ms: int | None
    frames_total: int
    dropped_frames: int
    frame_samples: int
    # API-only fields — omitted in lightweight WebSocket snapshots:
    latest_metrics: NotRequired[ClientMetrics]
    reset_count: NotRequired[int]
    last_reset_time: NotRequired[float | None]


class SpectrumSeriesPayload(TypedDict, total=False):
    combined_spectrum_amp_g: list[float]
    strength_metrics: VibrationStrengthMetrics
    freq: list[float]


class AlignmentInfoPayload(TypedDict):
    overlap_ratio: float
    aligned: bool
    shared_window_s: float
    sensor_count: int
    clock_synced: bool


class FrequencyWarningPayload(TypedDict):
    code: str
    message: str
    client_ids: list[str]


class SpectraPayload(TypedDict, total=False):
    frame_fingerprint: str
    freq: list[float]
    clients: dict[str, SpectrumSeriesPayload]
    alignment: AlignmentInfoPayload
    warning: FrequencyWarningPayload


WsErrorCode = Literal["payload_build_failed"]


class WsErrorPayload(TypedDict):
    error: WsErrorCode


class WsClientSelectionPayload(TypedDict, total=False):
    client_id: str | None


def _configure_pydantic_schema(typed_dict: Any, config: ConfigDict) -> None:
    typed_dict.__pydantic_config__ = config


_configure_pydantic_schema(WsClientSelectionPayload, ConfigDict(extra="ignore"))


class TimeAlignmentSensorPayload(TypedDict):
    start_s: float
    end_s: float
    duration_s: float
    synced: bool


class SharedWindowPayload(TypedDict):
    start_s: float
    end_s: float
    duration_s: float


class TimeAlignmentPayload(TypedDict):
    per_sensor: dict[str, TimeAlignmentSensorPayload]
    shared_window: SharedWindowPayload | None
    overlap_ratio: float
    aligned: bool
    clock_synced: bool
    sensors_included: list[str]
    sensors_excluded: list[str]


class RotationalSpeedValuePayload(TypedDict):
    rpm: float | None
    mode: str | None
    reason: str | None


class OrderBandPayload(TypedDict):
    key: str
    center_hz: float
    tolerance: float


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
