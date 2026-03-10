"""Test that ws_models Pydantic schema aligns with payload_types TypedDicts.

ws_models.py defines Pydantic models for WebSocket schema export and
validation, while payload_types.py defines TypedDict contracts for
runtime data flow.  Both must stay aligned — a field missing from one
side indicates an unintentional schema drift.
"""

from __future__ import annotations

from vibesensor.payload_types import (
    AlignmentInfoPayload,
    FrequencyWarningPayload,
    OrderBandPayload,
    RotationalSpeedsPayload,
    RotationalSpeedValuePayload,
    SpectrumSeriesPayload,
)
from vibesensor.payload_types import (
    LiveWsPayload as LiveWsPayloadTD,
)
from vibesensor.payload_types import (
    SpectraPayload as SpectraPayloadTD,
)
from vibesensor.ws_models import (
    AlignmentInfo,
    FrequencyWarning,
    OrderBand,
    RotationalSpeeds,
    RotationalSpeedValue,
    SpectrumSeries,
)
from vibesensor.ws_models import (
    LiveWsPayload as LiveWsPayloadPydantic,
)
from vibesensor.ws_models import (
    SpectraPayload as SpectraPayloadPydantic,
)


def _pydantic_field_names(model_cls: type) -> set[str]:
    """Extract field names from a Pydantic BaseModel class."""
    return set(model_cls.model_fields.keys())


def _typeddict_field_names(td_cls: type) -> set[str]:
    """Extract field names from a TypedDict class (including parents)."""
    return set(getattr(td_cls, "__annotations__", {}).keys())


def test_alignment_info_fields_match() -> None:
    td_fields = _typeddict_field_names(AlignmentInfoPayload)
    pd_fields = _pydantic_field_names(AlignmentInfo)
    assert td_fields == pd_fields, (
        f"AlignmentInfo drift — TypedDict-only: {td_fields - pd_fields}, "
        f"Pydantic-only: {pd_fields - td_fields}"
    )


def test_frequency_warning_fields_match() -> None:
    td_fields = _typeddict_field_names(FrequencyWarningPayload)
    pd_fields = _pydantic_field_names(FrequencyWarning)
    assert td_fields == pd_fields, (
        f"FrequencyWarning drift — TypedDict-only: {td_fields - pd_fields}, "
        f"Pydantic-only: {pd_fields - td_fields}"
    )


def test_order_band_fields_match() -> None:
    td_fields = _typeddict_field_names(OrderBandPayload)
    pd_fields = _pydantic_field_names(OrderBand)
    assert td_fields == pd_fields, (
        f"OrderBand drift — TypedDict-only: {td_fields - pd_fields}, "
        f"Pydantic-only: {pd_fields - td_fields}"
    )


def test_rotational_speed_value_fields_match() -> None:
    td_fields = _typeddict_field_names(RotationalSpeedValuePayload)
    pd_fields = _pydantic_field_names(RotationalSpeedValue)
    assert td_fields == pd_fields, (
        f"RotationalSpeedValue drift — TypedDict-only: {td_fields - pd_fields}, "
        f"Pydantic-only: {pd_fields - td_fields}"
    )


def test_rotational_speeds_fields_match() -> None:
    td_fields = _typeddict_field_names(RotationalSpeedsPayload)
    pd_fields = _pydantic_field_names(RotationalSpeeds)
    assert td_fields == pd_fields, (
        f"RotationalSpeeds drift — TypedDict-only: {td_fields - pd_fields}, "
        f"Pydantic-only: {pd_fields - td_fields}"
    )


def test_spectrum_series_common_fields_present() -> None:
    """SpectrumSeries and SpectrumSeriesPayload should share core data fields."""
    td_fields = _typeddict_field_names(SpectrumSeriesPayload)
    pd_fields = _pydantic_field_names(SpectrumSeries)
    # Both sides must have the core data fields
    core_fields = {"x", "y", "z", "combined_spectrum_amp_g", "strength_metrics"}
    assert core_fields <= td_fields, f"TypedDict missing core fields: {core_fields - td_fields}"
    assert core_fields <= pd_fields, f"Pydantic missing core fields: {core_fields - pd_fields}"


def test_spectra_payload_fields_match() -> None:
    """SpectraPayload variants must have identical field sets."""
    td_fields = _typeddict_field_names(SpectraPayloadTD)
    pd_fields = _pydantic_field_names(SpectraPayloadPydantic)
    assert td_fields == pd_fields, (
        f"SpectraPayload drift — TypedDict-only: {td_fields - pd_fields}, "
        f"Pydantic-only: {pd_fields - td_fields}"
    )


def test_live_ws_payload_fields_match() -> None:
    """LiveWsPayload variants must have identical field sets."""
    td_fields = _typeddict_field_names(LiveWsPayloadTD)
    pd_fields = _pydantic_field_names(LiveWsPayloadPydantic)
    assert td_fields == pd_fields, (
        f"LiveWsPayload drift — TypedDict-only: {td_fields - pd_fields}, "
        f"Pydantic-only: {pd_fields - td_fields}"
    )
