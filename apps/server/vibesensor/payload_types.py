from __future__ import annotations

from typing import TypeAlias

from typing_extensions import TypedDict

from vibesensor.core.vibration_strength import StrengthPeak, VibrationStrengthMetrics

from .json_types import JsonObject

# Bump this when the payload shape changes in a backwards-incompatible way.
SCHEMA_VERSION: str = "1"

IntakeStatsPayload: TypeAlias = JsonObject


class HealthDataLossPayload(TypedDict):
    tracked_clients: int
    affected_clients: int
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int


class HealthPersistencePayload(TypedDict):
    write_error: str | None
    analysis_in_progress: bool
    analysis_queue_depth: int
    analysis_queue_max_depth: int
    analysis_active_run_id: str | None
    analysis_started_at: float | None
    analysis_elapsed_s: float | None
    analysis_queue_oldest_age_s: float | None
    analyzing_run_count: int
    analyzing_oldest_age_s: float | None
    samples_written: int
    samples_dropped: int
    last_completed_run_id: str | None
    last_completed_run_error: str | None


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


class TimingHealthPayload(TypedDict, total=False):
    jitter_us_ema: float
    drift_us_total: float
    last_t0_us: int


class ClientApiRow(TypedDict):
    id: str
    mac_address: str
    name: str
    connected: bool
    location: str
    firmware_version: str
    sample_rate_hz: int
    frame_samples: int
    last_seen_age_ms: int | None
    data_addr: tuple[str, int] | None
    control_addr: tuple[str, int] | None
    frames_total: int
    dropped_frames: int
    duplicates_received: int
    queue_overflow_drops: int
    parse_errors: int
    server_queue_drops: int
    latest_metrics: ClientMetrics
    last_ack_cmd_seq: int | None
    last_ack_status: int | None
    reset_count: int
    last_reset_time: float | None
    timing_health: TimingHealthPayload


class SpectrumSeriesPayload(TypedDict, total=False):
    x: list[float]
    y: list[float]
    z: list[float]
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
    freq: list[float]
    clients: dict[str, SpectrumSeriesPayload]
    alignment: AlignmentInfoPayload
    warning: FrequencyWarningPayload


class WaveformPayload(TypedDict, total=False):
    t: list[float]
    x: list[float]
    y: list[float]
    z: list[float]


class SelectedSpectrumPayload(TypedDict, total=False):
    freq: list[float]
    x: list[float]
    y: list[float]
    z: list[float]
    combined_spectrum_amp_g: list[float]
    strength_metrics: VibrationStrengthMetrics


class SelectedClientPayload(TypedDict):
    client_id: str
    sample_rate_hz: int
    waveform: WaveformPayload
    spectrum: SelectedSpectrumPayload
    metrics: ClientMetrics


class DebugSpectrumStatsPayload(TypedDict):
    mean_g: list[float]
    std_g: list[float]
    min_g: list[float]
    max_g: list[float]


class DebugSpectrumTopBinPayload(TypedDict):
    bin: int
    freq_hz: float
    combined_amp_g: float
    x_amp_g: float
    y_amp_g: float
    z_amp_g: float


class DebugSpectrumErrorPayload(TypedDict):
    error: str
    count: int
    fft_n: int


class DebugSpectrumPayload(TypedDict, total=False):
    client_id: str
    sample_rate_hz: int
    fft_n: int
    fft_scale: float
    window: str
    spectrum_min_hz: float
    spectrum_max_hz: float
    freq_bins: int
    freq_resolution_hz: float
    raw_stats: DebugSpectrumStatsPayload
    detrended_std_g: list[float]
    vibration_strength_db: float
    top_bins_by_amplitude: list[DebugSpectrumTopBinPayload]
    strength_peaks: list[StrengthPeak]
    error: str
    count: int


class RawSamplesErrorPayload(TypedDict):
    error: str
    count: int


class RawSamplesPayload(TypedDict):
    client_id: str
    sample_rate_hz: int
    n_samples: int
    x: list[float]
    y: list[float]
    z: list[float]


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


class LiveWsPayload(TypedDict, total=False):
    schema_version: str
    server_time: str
    speed_mps: float | None
    clients: list[ClientApiRow]
    selected_client_id: str | None
    rotational_speeds: RotationalSpeedsPayload | None
    spectra: SpectraPayload
