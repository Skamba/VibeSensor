from __future__ import annotations

from typing import get_type_hints

from vibesensor.adapters.http.models.settings import CarResponse, CarUpsertRequest
from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.config.analysis_settings import ActiveCarAnalysisSettingsService
from vibesensor.infra.config.car_settings import CarSettingsService
from vibesensor.shared.analysis_settings_schema import ANALYSIS_SETTINGS_FIELDS
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)


def test_analysis_settings_payload_keys_match_snapshot_defaults() -> None:
    assert AnalysisSettingsPayload.__required_keys__ == frozenset()
    assert AnalysisSettingsPayload.__optional_keys__ == frozenset(ANALYSIS_SETTINGS_FIELDS)


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
    assert get_type_hints(CarSettingsService.active_car_aspects)["return"] == (
        AnalysisSettingsPayload | None
    )
    assert get_type_hints(CarSettingsService.update_active_car_aspects)["aspects"] is (
        AnalysisSettingsPayload
    )
    assert get_type_hints(CarSettingsService.update_active_car_aspects)["return"] is (
        AnalysisSettingsPayload
    )
    analysis_hints = get_type_hints(ActiveCarAnalysisSettingsService.update_active_car_aspects)
    assert (
        get_type_hints(ActiveCarAnalysisSettingsService.analysis_settings_snapshot)["return"]
        is AnalysisSettingsSnapshot
    )
    assert analysis_hints["aspects"] is (AnalysisSettingsPayload)
    assert analysis_hints["return"] is AnalysisSettingsPayload
