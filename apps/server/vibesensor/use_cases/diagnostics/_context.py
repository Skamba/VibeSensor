"""Canonical typed diagnostics run context."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    OrderReferenceSpec,
    RunMetadataSnapshot,
    Symptom,
)
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    ScalarSettings,
    analysis_settings_snapshot_items,
)
from vibesensor.shared.types.json_types import JsonObject

from ._types import Sample


@dataclass(frozen=True, slots=True)
class DiagnosticsSymptom:
    """Typed diagnostics-owned symptom input projected to the domain at the edge."""

    description: str = ""
    onset: str = ""
    context: str = ""

    @property
    def is_specified(self) -> bool:
        return bool(self.description)

    def as_domain_symptom(self) -> Symptom:
        if not self.description:
            return Symptom.unspecified()
        return Symptom(
            description=self.description,
            onset=self.onset,
            context=self.context,
        )


@dataclass(frozen=True, slots=True)
class DiagnosticsContext:
    """Canonical typed diagnostics context built once at metadata ingress."""

    run_metadata: RunMetadataSnapshot
    analysis_settings: AnalysisSettingsSnapshot = field(default_factory=AnalysisSettingsSnapshot)
    car: CarSnapshot | None = None
    symptom: DiagnosticsSymptom = field(default_factory=DiagnosticsSymptom)
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    report_date: str | None = None
    default_language: str = "en"
    fft_window_size_samples: int | None = None
    fft_window_type: str | None = None
    peak_picker_method: str | None = None
    accel_scale_g_per_lsb: float | None = None
    incomplete_for_order_analysis: bool = False
    tire_circumference_m_override: float | None = None
    explicit_engine_rpm: float | None = None
    units: JsonObject | None = None
    amplitude_definitions: JsonObject | None = None

    @property
    def run_id(self) -> str:
        return self.run_metadata.run_id

    @property
    def sensor_model(self) -> str | None:
        return self.run_metadata.sensor_model

    @property
    def firmware_version(self) -> str | None:
        return self.run_metadata.firmware_version

    @property
    def raw_sample_rate_hz(self) -> float | None:
        return self.run_metadata.raw_sample_rate_hz

    @property
    def feature_interval_s(self) -> float | None:
        return self.run_metadata.feature_interval_s

    @property
    def car_name(self) -> str | None:
        return self.car.name if self.car is not None else None

    @property
    def car_type(self) -> str | None:
        return self.car.car_type if self.car is not None else None

    @property
    def car_variant(self) -> str | None:
        return self.car.variant if self.car is not None else None

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        return self.analysis_settings.order_reference_spec

    @property
    def final_drive_ratio(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.final_drive_ratio > 0:
            return spec.final_drive_ratio
        ratio = self.analysis_settings.final_drive_ratio
        return ratio if ratio > 0 else None

    @property
    def current_gear_ratio(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and spec.current_gear_ratio > 0:
            return spec.current_gear_ratio
        ratio = self.analysis_settings.current_gear_ratio
        return ratio if ratio > 0 else None

    @property
    def tire_circumference_m(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and bool(getattr(spec, "supports_wheel_reference", False)):
            return spec.tire_circumference_m
        override = self.tire_circumference_m_override
        if override is not None and override > 0:
            return override
        return None

    @property
    def reference_complete(self) -> bool:
        spec = self.order_reference_spec
        return bool(
            self.raw_sample_rate_hz
            and self.tire_circumference_m
            and spec is not None
            and bool(getattr(spec, "is_complete", False))
            and (
                self.explicit_engine_rpm is not None
                or bool(getattr(spec, "has_engine_reference", False))
            )
        )

    @property
    def analysis_settings_items(self) -> ScalarSettings:
        return analysis_settings_snapshot_items(self.analysis_settings)

    def effective_order_reference_spec(
        self,
        sample: Sample | None = None,
    ) -> OrderReferenceSpec | None:
        """Return the base order-reference spec, optionally overridden by one sample."""
        spec = self.order_reference_spec
        if sample is None or spec is None:
            return spec
        final_drive_ratio = sample.final_drive_ratio
        gear_ratio = sample.gear
        if final_drive_ratio is None and gear_ratio is None:
            return spec
        return replace(
            spec,
            final_drive_ratio=(
                final_drive_ratio if final_drive_ratio is not None else spec.final_drive_ratio
            ),
            current_gear_ratio=(gear_ratio if gear_ratio is not None else spec.current_gear_ratio),
        )

__all__ = ["DiagnosticsContext", "DiagnosticsSymptom"]
