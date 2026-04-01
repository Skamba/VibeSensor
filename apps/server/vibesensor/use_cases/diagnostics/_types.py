"""Analysis-internal type aliases and value objects.

Boundary serialization TypedDicts (for example ``FindingPayload`` and
``AnalysisSummary``) live in shared boundary/type contract modules, not here.
This module is the diagnostics package's internal source of truth for
analysis-local value objects that should not depend on boundary payload
TypedDicts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict, cast

from vibesensor.domain import DrivingPhase, StrengthPeak
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject, JsonValue
from vibesensor.shared.types.sensor_frame import SensorFrame


@dataclass(frozen=True, slots=True)
class AnalysisSample:
    """A typed diagnostics-internal view of one recorded sample row."""

    t_s: float | None = None
    speed_kmh: float | None = None
    accel_x_g: float | None = None
    accel_y_g: float | None = None
    accel_z_g: float | None = None
    vibration_strength_db: float | None = None
    strength_bucket: str = ""
    strength_floor_amp_g: float | None = None
    top_peaks: tuple[StrengthPeak, ...] = ()
    dominant_freq_hz: float | None = None
    location: str = ""
    client_name: str = ""
    client_id: str = ""
    engine_rpm: float | None = None
    engine_rpm_source: str = ""
    engine_rpm_estimated: float | None = None
    final_drive_ratio: float | None = None
    gear: float | None = None
    frames_dropped_total: float | None = None
    queue_overflow_drops: float | None = None

    @classmethod
    def from_dict(cls, raw: JsonObject) -> AnalysisSample:
        raw_top_peaks = raw.get("top_peaks")
        top_peaks: list[StrengthPeak] = []
        if isinstance(raw_top_peaks, Sequence) and not isinstance(
            raw_top_peaks,
            (str, bytes, bytearray),
        ):
            for peak in raw_top_peaks:
                if isinstance(peak, Mapping):
                    top_peaks.append(
                        StrengthPeak.from_dict(cast(Mapping[str, object], peak)),
                    )
        return cls(
            t_s=_as_float(raw.get("t_s")),
            speed_kmh=_as_float(raw.get("speed_kmh")),
            accel_x_g=_as_float(raw.get("accel_x_g")),
            accel_y_g=_as_float(raw.get("accel_y_g")),
            accel_z_g=_as_float(raw.get("accel_z_g")),
            vibration_strength_db=_as_float(raw.get("vibration_strength_db")),
            strength_bucket=str(raw.get("strength_bucket") or ""),
            strength_floor_amp_g=_as_float(raw.get("strength_floor_amp_g")),
            top_peaks=tuple(top_peaks),
            dominant_freq_hz=_as_float(raw.get("dominant_freq_hz")),
            location=str(raw.get("location") or ""),
            client_name=str(raw.get("client_name") or ""),
            client_id=str(raw.get("client_id") or ""),
            engine_rpm=_as_float(raw.get("engine_rpm")),
            engine_rpm_source=str(raw.get("engine_rpm_source") or ""),
            engine_rpm_estimated=_as_float(raw.get("engine_rpm_estimated")),
            final_drive_ratio=_as_float(raw.get("final_drive_ratio")),
            gear=_as_float(raw.get("gear")),
            frames_dropped_total=_as_float(raw.get("frames_dropped_total")),
            queue_overflow_drops=_as_float(raw.get("queue_overflow_drops")),
        )

    @classmethod
    def from_sensor_frame(cls, sample: SensorFrame) -> AnalysisSample:
        return cls(
            t_s=sample.t_s,
            speed_kmh=sample.speed_kmh,
            accel_x_g=sample.accel_x_g,
            accel_y_g=sample.accel_y_g,
            accel_z_g=sample.accel_z_g,
            vibration_strength_db=sample.vibration_strength_db,
            strength_bucket=sample.strength_bucket or "",
            strength_floor_amp_g=sample.strength_floor_amp_g,
            top_peaks=sample.top_peaks,
            dominant_freq_hz=sample.dominant_freq_hz,
            location=sample.location,
            client_name=sample.client_name,
            client_id=sample.client_id,
            engine_rpm=sample.engine_rpm,
            engine_rpm_source=sample.engine_rpm_source,
            final_drive_ratio=sample.final_drive_ratio,
            gear=sample.gear,
            frames_dropped_total=float(sample.frames_dropped_total),
            queue_overflow_drops=float(sample.queue_overflow_drops),
        )

    def to_json_object(self) -> JsonObject:
        top_peaks = cast(
            list[JsonValue],
            [peak.to_dict() for peak in self.top_peaks],
        )
        raw: JsonObject = {
            "t_s": self.t_s,
            "speed_kmh": self.speed_kmh,
            "accel_x_g": self.accel_x_g,
            "accel_y_g": self.accel_y_g,
            "accel_z_g": self.accel_z_g,
            "vibration_strength_db": self.vibration_strength_db,
            "strength_bucket": self.strength_bucket,
            "strength_floor_amp_g": self.strength_floor_amp_g,
            "top_peaks": top_peaks,
            "dominant_freq_hz": self.dominant_freq_hz,
            "location": self.location,
            "client_name": self.client_name,
            "client_id": self.client_id,
            "engine_rpm": self.engine_rpm,
            "engine_rpm_source": self.engine_rpm_source,
            "engine_rpm_estimated": self.engine_rpm_estimated,
            "final_drive_ratio": self.final_drive_ratio,
            "gear": self.gear,
            "frames_dropped_total": self.frames_dropped_total,
            "queue_overflow_drops": self.queue_overflow_drops,
        }
        return raw


type Sample = AnalysisSample
type AnalysisSampleInput = AnalysisSample | SensorFrame | JsonObject


def analysis_samples_to_json_objects(samples: Sequence[Sample]) -> list[JsonObject]:
    """Project typed diagnostics samples into JSON-safe boundary rows."""

    return [sample.to_json_object() for sample in samples]


def normalize_analysis_samples(
    samples: Sequence[AnalysisSampleInput],
) -> list[AnalysisSample]:
    """Normalize arbitrary input rows once to typed diagnostics samples."""

    return [ensure_analysis_sample(sample) for sample in samples]


def ensure_analysis_sample(sample: AnalysisSampleInput) -> AnalysisSample:
    """Normalize one sample row to the typed diagnostics contract."""

    if isinstance(sample, AnalysisSample):
        return sample
    if isinstance(sample, SensorFrame):
        return AnalysisSample.from_sensor_frame(sample)
    return AnalysisSample.from_dict(sample)


def ensure_analysis_samples(samples: Sequence[AnalysisSampleInput]) -> list[AnalysisSample]:
    """Normalize arbitrary sample rows to typed diagnostics samples."""

    return normalize_analysis_samples(samples)


class AccelStatistics(TypedDict):
    accel_x_vals: list[float]
    accel_y_vals: list[float]
    accel_z_vals: list[float]
    accel_mag_vals: list[float]
    amp_metric_values: list[float]
    sat_count: int
    sensor_limit: float | None
    x_mean: float | None
    x_var: float | None
    y_mean: float | None
    y_var: float | None
    z_mean: float | None
    z_var: float | None


type PhaseLabel = DrivingPhase | str
type PhaseLabels = Sequence[PhaseLabel]
