"""Run metadata snapshot used for persisted recording identification fields."""

from __future__ import annotations

from dataclasses import dataclass

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
