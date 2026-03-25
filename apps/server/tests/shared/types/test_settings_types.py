from __future__ import annotations

from typing import get_type_hints

from vibesensor.adapters.http.models.settings import CarResponse, CarUpsertRequest
from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.config.car_settings import CarSettingsService
from vibesensor.infra.config.settings_store import SettingsStore
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)


def test_analysis_settings_payload_keys_match_snapshot_defaults() -> None:
    assert AnalysisSettingsPayload.__required_keys__ == frozenset()
    assert AnalysisSettingsPayload.__optional_keys__ == frozenset(AnalysisSettingsSnapshot.DEFAULTS)


def test_analysis_settings_payload_projection_keeps_only_supported_keys() -> None:
    payload = analysis_settings_payload_from_mapping(
        {
            "tire_width_mm": 255.0,
            "rim_in": 19.0,
            "unsupported_key": 999.0,
        }
    )

    assert payload == {
        "tire_width_mm": 255.0,
        "rim_in": 19.0,
    }


def test_http_and_store_annotations_use_analysis_settings_payload() -> None:
    assert get_type_hints(CarUpsertRequest)["aspects"] == AnalysisSettingsPayload | None
    assert get_type_hints(CarResponse)["aspects"] is AnalysisSettingsPayload
    assert get_type_hints(SettingsStore.active_car_aspects)["return"] == (
        AnalysisSettingsPayload | None
    )
    assert get_type_hints(SettingsStore.update_active_car_aspects)["aspects"] is (
        AnalysisSettingsPayload
    )
    assert get_type_hints(SettingsStore.update_active_car_aspects)["return"] is (
        AnalysisSettingsPayload
    )
    assert get_type_hints(CarSettingsService.active_car_aspects)["return"] == (
        AnalysisSettingsPayload | None
    )
    assert get_type_hints(CarSettingsService.update_active_car_aspects)["aspects"] is (
        AnalysisSettingsPayload
    )
    assert get_type_hints(CarSettingsService.update_active_car_aspects)["return"] is (
        AnalysisSettingsPayload
    )
