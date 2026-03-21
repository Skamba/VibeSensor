"""Run metadata snapshot used for persisted recording identification fields."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ._snapshot_parse import _int_or, _opt_float_raw, _opt_str, _str_or

__all__ = ["RunMetadataSnapshot"]


@dataclass(frozen=True, slots=True)
class RunMetadataSnapshot:
    """Typed internal representation of recording-identification metadata.

    Covers fields NOT already owned by ``AnalysisSettingsSnapshot``,
    ``CarSnapshot``, ``RunContextSnapshot``, or ``OrderReferenceSpec``.
    """

    run_id: str = ""
    case_id: str = ""
    sensor_mac: str | None = None
    sensor_model: str | None = None
    firmware_version: str | None = None
    raw_sample_rate_hz: float | None = None
    feature_interval_s: float | None = None
    summary_version: int = 1

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be a non-empty string")
        if self.summary_version < 1:
            raise ValueError("summary_version must be >= 1")

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> RunMetadataSnapshot:
        """Parse from a raw metadata mapping."""
        return cls(
            run_id=_str_or(raw, "run_id", _str_or(raw, "recording_id", "")),
            case_id=_str_or(raw, "case_id", ""),
            sensor_mac=_opt_str(raw, "sensor_mac"),
            sensor_model=_opt_str(raw, "sensor_model"),
            firmware_version=_opt_str(raw, "firmware_version"),
            raw_sample_rate_hz=_opt_float_raw(raw, "raw_sample_rate_hz"),
            feature_interval_s=_opt_float_raw(raw, "feature_interval_s"),
            summary_version=_int_or(raw, "_summary_version", 1),
        )
