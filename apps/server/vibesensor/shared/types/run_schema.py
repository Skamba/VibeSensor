"""Shared JSONL run-schema constants and canonical typed metadata contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from vibesensor.shared.types.json_types import JsonObject

__all__ = [
    "FFT_WINDOW_TYPE",
    "PEAK_PICKER_METHOD",
    "RUN_END_TYPE",
    "RUN_METADATA_TYPE",
    "RUN_SAMPLE_TYPE",
    "RUN_SCHEMA_VERSION",
    "RunMetadata",
]

RUN_SCHEMA_VERSION: Final[str] = "v2-jsonl"
RUN_METADATA_TYPE: Final[str] = "run_metadata"
RUN_SAMPLE_TYPE: Final[str] = "sample"
RUN_END_TYPE: Final[str] = "run_end"
FFT_WINDOW_TYPE: str = "hann"
PEAK_PICKER_METHOD: str = "canonical_strength_metrics_module"


@dataclass(slots=True)
class RunMetadata:
    """Typed persisted run metadata.

    Stable header fields live on explicit dataclass attributes. Additional
    persisted run/context/settings metadata stays in ``extras`` so history and
    post-analysis code can keep a typed object route without losing the richer
    stored payload.
    """

    record_type: str
    schema_version: str
    run_id: str
    start_time_utc: str
    end_time_utc: str | None
    sensor_model: str
    firmware_version: str | None
    raw_sample_rate_hz: int | None
    feature_interval_s: float | None
    fft_window_size_samples: int | None
    fft_window_type: str | None
    peak_picker_method: str
    accel_scale_g_per_lsb: float | None
    incomplete_for_order_analysis: bool
    extras: JsonObject = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        start_time_utc: str,
        sensor_model: str,
        raw_sample_rate_hz: int | None,
        feature_interval_s: float | None,
        fft_window_size_samples: int | None,
        accel_scale_g_per_lsb: float | None,
        firmware_version: str | None = None,
        end_time_utc: str | None = None,
        incomplete_for_order_analysis: bool = False,
    ) -> RunMetadata:
        """Construct canonical run metadata for a newly recorded run."""
        return cls(
            record_type=RUN_METADATA_TYPE,
            schema_version=RUN_SCHEMA_VERSION,
            run_id=run_id,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
            sensor_model=sensor_model,
            firmware_version=firmware_version,
            raw_sample_rate_hz=raw_sample_rate_hz,
            feature_interval_s=feature_interval_s,
            fft_window_size_samples=fft_window_size_samples,
            fft_window_type=FFT_WINDOW_TYPE,
            peak_picker_method=PEAK_PICKER_METHOD,
            accel_scale_g_per_lsb=accel_scale_g_per_lsb,
            incomplete_for_order_analysis=bool(incomplete_for_order_analysis),
            extras={},
        )

    @property
    def language(self) -> str | None:
        """Return the normalized persisted language code from metadata extras."""
        value = self.extras.get("language")
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return None

    @property
    def car_name(self) -> str | None:
        """Return the normalized persisted car name from metadata extras."""
        value = None
        active_car_snapshot = self.extras.get("active_car_snapshot")
        if isinstance(active_car_snapshot, Mapping):
            value = active_car_snapshot.get("name") or active_car_snapshot.get("type")
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return None
