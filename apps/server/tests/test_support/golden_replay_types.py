"""Golden replay fixture DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from test_support.core import FINAL_DRIVE, GEAR_RATIO
from vibesensor.shared.types.raw_capture import RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.whole_run_analysis import WholeRunArtifactManifest

GoldenUnavailableReason = Literal["missing_speed", "missing_rpm"]
GoldenScenarioGroup = Literal[
    "baseline",
    "wheel",
    "driveline",
    "engine",
    "resonance",
    "road_shock",
    "transient",
    "data_quality",
]

_DEFAULT_DURATION_S = 8.0
_DEFAULT_SPEED_KMH = 80.0
_DEFAULT_ENGINE_RPM = 1500.0
_SAMPLE_RATE_HZ = 256
_FFT_WINDOW_SIZE_SAMPLES = 256


@dataclass(frozen=True, slots=True)
class GoldenReplayExpected:
    """Stable assertions attached to one generated replay fixture."""

    suspected_source: str | None
    strongest_location: str | None = None
    confidence_range: tuple[float, float] = (0.0, 1.0)
    confidence_label_key: str | None = None
    unavailable_reasons: tuple[GoldenUnavailableReason, ...] = ()
    tolerance_bands: Mapping[str, tuple[float, float]] | None = None
    max_false_positive_confidence: float | None = None
    required_warning_codes: tuple[str, ...] = ()
    required_metadata_minimums: Mapping[str, float] | None = None


@dataclass(frozen=True, slots=True)
class GoldenReplayFixture:
    """Compact fixture format; raw waveform and summary rows are generated."""

    case_id: str
    title: str
    group: GoldenScenarioGroup
    seed: int
    expected: GoldenReplayExpected
    primary_frequency_hz: float | None = None
    strongest_sensor: str | None = None
    signal_amp_g: float = 0.08
    transfer_amp_g: float = 0.024
    speed_kmh: float | None = _DEFAULT_SPEED_KMH
    speed_sweep_kmh: tuple[float, float] | None = None
    speed_source: str = "gps"
    engine_rpm: float | None = _DEFAULT_ENGINE_RPM
    final_drive_ratio: float | None = FINAL_DRIVE
    current_gear_ratio: float | None = GEAR_RATIO
    duration_s: float = _DEFAULT_DURATION_S
    sample_rate_hz: int = _SAMPLE_RATE_HZ
    fft_window_size_samples: int = _FFT_WINDOW_SIZE_SAMPLES
    transient_duration_s: float = 0.0
    transient_frequency_hz: float | None = None
    fast_ci: bool = True

    def build(self, *, duration_s: float | None = None) -> GoldenReplayRun:
        from test_support.golden_replay_capture import build_golden_replay_run

        return build_golden_replay_run(self, duration_s=duration_s)


@dataclass(frozen=True, slots=True)
class GoldenReplayRun:
    fixture: GoldenReplayFixture
    run_id: str
    metadata: RunMetadata
    samples: list[SensorFrame]
    raw_capture: RawRunCapture


@dataclass(frozen=True, slots=True)
class GoldenReplayResult:
    fixture: GoldenReplayFixture
    analysis: dict[str, object]
    manifest: WholeRunArtifactManifest
    artifact_contents: Mapping[str, bytes]


@dataclass(frozen=True, slots=True)
class GoldenReplayBenchmarkResult:
    elapsed_s: float
    peak_memory_bytes: int
    result: GoldenReplayResult
