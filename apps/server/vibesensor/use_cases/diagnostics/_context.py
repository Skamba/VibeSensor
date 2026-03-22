"""Typed diagnostics-internal run context.

Boundary metadata arrives as a raw JSON mapping from JSONL/history storage, but the
analysis pipeline should consume a typed object once that payload crosses the
boundary. ``DiagnosticsContext`` centralizes that normalization while preserving
round-trippable metadata for explicit serializer edges.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from types import MappingProxyType
from typing import TypeAlias, cast

from vibesensor.domain import (
    Car,
    ConfigurationSnapshot,
    OrderReferenceSpec,
    RunContextSnapshot,
    RunMetadataSnapshot,
    Symptom,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject

from ._types import Sample

ScalarSettingValue: TypeAlias = int | float | bool | str
ScalarSettings: TypeAlias = tuple[tuple[str, ScalarSettingValue], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticsContext:
    """Canonical typed diagnostics context built once at raw-metadata ingress."""

    run_metadata: RunMetadataSnapshot
    run_context: RunContextSnapshot
    start_time_utc: str | None = None
    end_time_utc: str | None = None
    report_date: str | None = None
    default_language: str = "en"
    fft_window_size_samples: int | None = None
    fft_window_type: str | None = None
    peak_picker_method: str | None = None
    accel_scale_g_per_lsb: float | None = None
    incomplete_for_order_analysis: bool = False
    symptom_description: str = ""
    symptom_onset: str = ""
    symptom_context: str = ""
    tire_circumference_m_override: float | None = None
    explicit_engine_rpm: float | None = None
    scalar_analysis_settings: ScalarSettings = ()
    _final_drive_ratio: float | None = None
    _current_gear_ratio: float | None = None
    _car_name: str | None = None
    _car_type: str | None = None
    _car_variant: str | None = None
    _fallback_order_reference_spec: OrderReferenceSpec | None = None
    _boundary_metadata: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._boundary_metadata, MappingProxyType):
            object.__setattr__(
                self,
                "_boundary_metadata",
                MappingProxyType(dict(self._boundary_metadata)),
            )

    @classmethod
    def from_metadata(
        cls,
        metadata: Mapping[str, object],
        *,
        file_name: str = "run",
    ) -> DiagnosticsContext:
        """Decode one raw metadata mapping into the diagnostics context."""
        raw_metadata = dict(metadata)
        run_metadata_payload = dict(raw_metadata)
        if not _non_empty_text(run_metadata_payload.get("run_id")) and not _non_empty_text(
            run_metadata_payload.get("recording_id"),
        ):
            run_metadata_payload["run_id"] = f"run-{file_name}"
        run_context = RunContextSnapshot.from_dict(raw_metadata)
        order_reference_spec = OrderReferenceSpec.from_settings(raw_metadata)
        run_context_spec = run_context.order_reference_spec
        final_drive_ratio = _as_float(raw_metadata.get("final_drive_ratio"))
        if final_drive_ratio is None and run_context_spec is not None:
            final_drive_ratio = _as_float(getattr(run_context_spec, "final_drive_ratio", None))
        current_gear_ratio = _as_float(raw_metadata.get("current_gear_ratio"))
        if current_gear_ratio is None and run_context_spec is not None:
            current_gear_ratio = _as_float(getattr(run_context_spec, "current_gear_ratio", None))
        return cls(
            run_metadata=RunMetadataSnapshot.from_dict(run_metadata_payload),
            run_context=run_context,
            start_time_utc=_non_empty_text(raw_metadata.get("start_time_utc")),
            end_time_utc=_non_empty_text(raw_metadata.get("end_time_utc")),
            report_date=_non_empty_text(raw_metadata.get("report_date")),
            default_language=_normalized_language(raw_metadata.get("language")),
            fft_window_size_samples=_as_int(raw_metadata.get("fft_window_size_samples")),
            fft_window_type=_non_empty_text(raw_metadata.get("fft_window_type")),
            peak_picker_method=_non_empty_text(raw_metadata.get("peak_picker_method")),
            accel_scale_g_per_lsb=_as_float(raw_metadata.get("accel_scale_g_per_lsb")),
            incomplete_for_order_analysis=bool(raw_metadata.get("incomplete_for_order_analysis")),
            symptom_description=_non_empty_text(
                raw_metadata.get("symptom") or raw_metadata.get("complaint"),
            )
            or "",
            symptom_onset=_non_empty_text(raw_metadata.get("symptom_onset")) or "",
            symptom_context=_non_empty_text(raw_metadata.get("symptom_context")) or "",
            tire_circumference_m_override=_as_float(raw_metadata.get("tire_circumference_m")),
            explicit_engine_rpm=_as_float(raw_metadata.get("engine_rpm")),
            scalar_analysis_settings=_scalar_analysis_settings(raw_metadata),
            _final_drive_ratio=final_drive_ratio,
            _current_gear_ratio=current_gear_ratio,
            _car_name=_non_empty_text(raw_metadata.get("car_name") or raw_metadata.get("name")),
            _car_type=_non_empty_text(raw_metadata.get("car_type")),
            _car_variant=_non_empty_text(
                raw_metadata.get("car_variant") or raw_metadata.get("variant"),
            ),
            _fallback_order_reference_spec=order_reference_spec,
            _boundary_metadata=cast(Mapping[str, object], raw_metadata),
        )

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
        return self.run_context.car_name or self._car_name

    @property
    def car_type(self) -> str | None:
        return self.run_context.car_type or self._car_type

    @property
    def car_variant(self) -> str | None:
        return self.run_context.car_variant or self._car_variant

    @property
    def order_reference_spec(self) -> OrderReferenceSpec | None:
        run_context_spec = self.run_context.order_reference_spec
        fallback_spec = self._fallback_order_reference_spec
        if _reference_spec_score(fallback_spec) > _reference_spec_score(run_context_spec):
            return fallback_spec
        return run_context_spec or fallback_spec

    @property
    def final_drive_ratio(self) -> float | None:
        if self._final_drive_ratio is not None:
            return self._final_drive_ratio
        spec = self.order_reference_spec
        return _as_float(getattr(spec, "final_drive_ratio", None)) if spec is not None else None

    @property
    def current_gear_ratio(self) -> float | None:
        if self._current_gear_ratio is not None:
            return self._current_gear_ratio
        spec = self.order_reference_spec
        return _as_float(getattr(spec, "current_gear_ratio", None)) if spec is not None else None

    @property
    def tire_circumference_m(self) -> float | None:
        spec = self.order_reference_spec
        if spec is not None and bool(getattr(spec, "supports_wheel_reference", False)):
            return _as_float(getattr(spec, "tire_circumference_m", None))
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

    def to_metadata_dict(self) -> JsonObject:
        """Rehydrate the persisted metadata shape for boundary serializers."""
        metadata: dict[str, object] = dict(self._boundary_metadata)
        metadata["run_id"] = self.run_id
        metadata["case_id"] = self.run_metadata.case_id
        metadata["sensor_mac"] = self.run_metadata.sensor_mac
        metadata["sensor_model"] = self.sensor_model
        metadata["firmware_version"] = self.firmware_version
        metadata["raw_sample_rate_hz"] = self.raw_sample_rate_hz
        metadata["feature_interval_s"] = self.feature_interval_s
        metadata["_summary_version"] = self.run_metadata.summary_version
        metadata["start_time_utc"] = self.start_time_utc
        metadata["end_time_utc"] = self.end_time_utc
        if self.report_date is not None or "report_date" in metadata:
            metadata["report_date"] = self.report_date
        if self.fft_window_size_samples is not None or "fft_window_size_samples" in metadata:
            metadata["fft_window_size_samples"] = self.fft_window_size_samples
        if self.fft_window_type is not None or "fft_window_type" in metadata:
            metadata["fft_window_type"] = self.fft_window_type
        if self.peak_picker_method is not None or "peak_picker_method" in metadata:
            metadata["peak_picker_method"] = self.peak_picker_method
        if self.accel_scale_g_per_lsb is not None or "accel_scale_g_per_lsb" in metadata:
            metadata["accel_scale_g_per_lsb"] = self.accel_scale_g_per_lsb
        metadata["incomplete_for_order_analysis"] = self.incomplete_for_order_analysis
        if "language" in metadata or self.default_language != "en":
            metadata["language"] = self.default_language
        if self.explicit_engine_rpm is not None or "engine_rpm" in metadata:
            metadata["engine_rpm"] = self.explicit_engine_rpm

        settings_dict = asdict(self.run_context.analysis_settings)
        for key, value in settings_dict.items():
            if key in metadata or value:
                metadata[key] = value
        tire_circumference_m = self.tire_circumference_m
        if tire_circumference_m is not None or "tire_circumference_m" in metadata:
            metadata["tire_circumference_m"] = tire_circumference_m

        if "analysis_settings_snapshot" in metadata or any(
            value != 0.0 for value in settings_dict.values()
        ):
            metadata.update(self.run_context.to_metadata_dict())

        if self.run_context.has_car_context:
            metadata["active_car_id"] = self.run_context.active_car_id
            metadata["car_name"] = self.run_context.car_name
            metadata["car_type"] = self.run_context.car_type
            metadata["car_variant"] = self.run_context.car_variant
        else:
            if self.car_name is not None or "car_name" in metadata:
                metadata["car_name"] = self.car_name
            if self.car_type is not None or "car_type" in metadata:
                metadata["car_type"] = self.car_type
            if self.car_variant is not None or "car_variant" in metadata:
                metadata["car_variant"] = self.car_variant
        return cast(JsonObject, metadata)

    def to_configuration_snapshot(self) -> ConfigurationSnapshot:
        spec = self.order_reference_spec
        return ConfigurationSnapshot(
            sensor_model=self.sensor_model,
            firmware_version=self.firmware_version,
            raw_sample_rate_hz=self.raw_sample_rate_hz,
            feature_interval_s=self.feature_interval_s,
            final_drive_ratio=self.final_drive_ratio,
            tire_spec=spec.tire_spec if spec is not None else None,
            metadata=self.to_metadata_dict(),
        )

    def to_car(self) -> Car | None:
        spec = self.order_reference_spec
        car_snapshot = self.run_context.car
        if not (self.car_name or self.car_type or self.car_variant or spec is not None):
            return None
        return Car(
            id=car_snapshot.car_id if car_snapshot is not None else None,
            name=self.car_name or "Unnamed Car",
            car_type=self.car_type or "sedan",
            aspects=car_snapshot.aspects if car_snapshot is not None else None,
            variant=self.car_variant or None,
            order_reference_spec=spec,
        )

    def to_symptom(self) -> Symptom:
        if not self.symptom_description:
            return Symptom.unspecified()
        return Symptom(
            description=self.symptom_description,
            onset=self.symptom_onset,
            context=self.symptom_context,
        )


def _non_empty_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalized_language(value: object) -> str:
    text = _non_empty_text(value)
    return text.lower() if text is not None else "en"


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _reference_spec_score(spec: OrderReferenceSpec | None) -> int:
    if spec is None:
        return 0
    return (
        int(bool(getattr(spec, "supports_wheel_reference", False)))
        + int(bool(getattr(spec, "supports_driveshaft_reference", False)))
        + int(
            bool(getattr(spec, "supports_engine_reference", False)),
        )
    )


def _scalar_analysis_settings(metadata: Mapping[str, object]) -> ScalarSettings:
    raw_settings = metadata.get("analysis_settings")
    if not isinstance(raw_settings, Mapping):
        return ()
    scalar_items: list[tuple[str, ScalarSettingValue]] = []
    for key, value in sorted(raw_settings.items()):
        if isinstance(key, str) and isinstance(value, (int, float, bool, str)):
            scalar_items.append((key, value))
    return tuple(scalar_items)


__all__ = ["DiagnosticsContext"]
