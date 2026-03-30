"""Shared JSONL run-schema constants and typed metadata contract."""

from __future__ import annotations

import logging
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

_LOGGER = logging.getLogger(__name__)
_RUN_METADATA_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "record_type",
        "schema_version",
        "run_id",
        "start_time_utc",
        "end_time_utc",
        "sensor_model",
        "firmware_version",
        "raw_sample_rate_hz",
        "feature_interval_s",
        "fft_window_size_samples",
        "fft_window_type",
        "peak_picker_method",
        "accel_scale_g_per_lsb",
        "incomplete_for_order_analysis",
    }
)

RUN_SCHEMA_VERSION: Final[str] = "v2-jsonl"
RUN_METADATA_TYPE: Final[str] = "run_metadata"
RUN_SAMPLE_TYPE: Final[str] = "sample"
RUN_END_TYPE: Final[str] = "run_end"
FFT_WINDOW_TYPE: str = "hann"
PEAK_PICKER_METHOD: str = "canonical_strength_metrics_module"


def _as_str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


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

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunMetadata:
        """Normalize a raw persisted metadata mapping into the typed dataclass."""
        from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none

        run_id = str(data.get("run_id", ""))
        if not run_id:
            _LOGGER.warning("RunMetadata.from_dict: missing or empty run_id in record %r", data)
        return cls(
            record_type=str(data.get("record_type", RUN_METADATA_TYPE)),
            schema_version=str(data.get("schema_version", RUN_SCHEMA_VERSION)),
            run_id=run_id,
            start_time_utc=str(data.get("start_time_utc", "")),
            end_time_utc=_as_str_or_none(data.get("end_time_utc")),
            sensor_model=str(data.get("sensor_model", "unknown")),
            firmware_version=(str(data.get("firmware_version", "")).strip() or None),
            raw_sample_rate_hz=as_int_or_none(data.get("raw_sample_rate_hz")),
            feature_interval_s=as_float_or_none(data.get("feature_interval_s")),
            fft_window_size_samples=as_int_or_none(data.get("fft_window_size_samples")),
            fft_window_type=_as_str_or_none(data.get("fft_window_type")),
            peak_picker_method=str(data.get("peak_picker_method", "")),
            accel_scale_g_per_lsb=as_float_or_none(data.get("accel_scale_g_per_lsb")),
            incomplete_for_order_analysis=bool(data.get("incomplete_for_order_analysis", False)),
            extras={
                key: value
                for key, value in data.items()
                if key not in _RUN_METADATA_FIELD_KEYS
                and (value is None or isinstance(value, (bool, int, float, str, list, dict)))
            },
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
        value = self.extras.get("car_name") or self.extras.get("name")
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return None

    def to_dict(self) -> JsonObject:
        """Serialize typed run metadata back to the canonical JSONL header shape."""
        payload: JsonObject = {
            "record_type": self.record_type,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "start_time_utc": self.start_time_utc,
            "end_time_utc": self.end_time_utc,
            "sensor_model": self.sensor_model,
            "firmware_version": self.firmware_version,
            "raw_sample_rate_hz": self.raw_sample_rate_hz,
            "feature_interval_s": self.feature_interval_s,
            "fft_window_size_samples": self.fft_window_size_samples,
            "fft_window_type": self.fft_window_type,
            "peak_picker_method": self.peak_picker_method,
            "accel_scale_g_per_lsb": self.accel_scale_g_per_lsb,
            "incomplete_for_order_analysis": self.incomplete_for_order_analysis,
        }
        payload.update(self.extras)
        return payload
