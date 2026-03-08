from __future__ import annotations

from typing import TypeAlias

from typing_extensions import TypedDict
from vibesensor_core.vibration_strength import StrengthPeak, VibrationStrengthMetrics

from .analysis import Finding
from .json_types import JsonObject

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


MetricEntry: TypeAlias = AxisMetrics | CombinedMetrics | VibrationStrengthMetrics
MetricsPayload: TypeAlias = dict[str, MetricEntry]


class StrengthMetricsPayload(TypedDict, total=False):
    combined_spectrum_amp_g: list[float]
    vibration_strength_db: float
    peak_amp_g: float
    noise_floor_amp_g: float
    strength_bucket: str | None
    top_peaks: list[StrengthPeak]


class TimingHealthPayload(TypedDict):
    jitter_us_ema: float
    drift_us_total: float


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
    latest_metrics: MetricsPayload
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
    strength_metrics: StrengthMetricsPayload
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
    strength_metrics: StrengthMetricsPayload


class SelectedClientPayload(TypedDict):
    client_id: str
    sample_rate_hz: int
    waveform: WaveformPayload
    spectrum: SelectedSpectrumPayload
    metrics: MetricsPayload


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


class MatrixCellPayload(TypedDict):
    count: int
    seconds: float
    contributors: dict[str, int]


MatrixPayload: TypeAlias = dict[str, dict[str, MatrixCellPayload]]


class DiagnosticLevelPayload(TypedDict, total=False):
    bucket_key: str
    strength_db: float
    sensor_label: str
    sensor_location: str
    class_key: str
    peak_hz: float
    confidence: float
    agreement_count: int
    sensor_count: int


class DiagnosticsLevelsPayload(TypedDict):
    by_source: dict[str, DiagnosticLevelPayload]
    by_sensor: dict[str, DiagnosticLevelPayload]
    by_location: dict[str, DiagnosticLevelPayload]


class StrengthBandPayload(TypedDict):
    key: str
    min_db: float
    max_db: float | None
    labelKey: str


class DiagnosticEventPayload(TypedDict, total=False):
    event_id: int
    kind: str
    class_key: str
    severity_key: str | None
    sensor_id: str
    sensor_label: str
    sensor_labels: list[str]
    sensor_count: int
    peak_hz: float
    peak_amp: float
    peak_amp_g: float
    vibration_strength_db: float


class LiveDiagnosticsPayload(TypedDict):
    diagnostics_sequence: int
    matrix: MatrixPayload
    events: list[DiagnosticEventPayload]
    strength_bands: list[StrengthBandPayload]
    levels: DiagnosticsLevelsPayload
    findings: list[Finding]
    top_finding: Finding | None
    driving_phase: str
    error: str | None


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
    diagnostics: LiveDiagnosticsPayload
