"""Exercise config-derivation defaults and active-car projection behavior."""

from __future__ import annotations

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.infra.config.settings_derivation import SettingsDerivationService
from vibesensor.infra.config.settings_store import SettingsStore


def test_derivation_service_returns_defaults_without_active_car() -> None:
    service = SettingsDerivationService(
        active_car_aspects=lambda: None,
        active_car_snapshot=lambda: None,
    )

    snapshot = service.analysis_settings_snapshot()

    assert snapshot.tire_width_mm == AnalysisSettingsSnapshot.DEFAULTS["tire_width_mm"]
    assert snapshot.rim_in == AnalysisSettingsSnapshot.DEFAULTS["rim_in"]
    assert service.active_car_snapshot() is None


def test_derivation_service_merges_active_car_aspects_with_defaults() -> None:
    store = SettingsStore()
    created = store.add_car({"name": "Primary", "aspects": {"tire_width_mm": 255.0}})
    store.set_active_car(created.cars[0]["id"])
    service = SettingsDerivationService(
        active_car_aspects=store.active_car_aspects,
        active_car_snapshot=store.active_car_snapshot,
    )

    snapshot = service.analysis_settings_snapshot()

    assert snapshot.tire_width_mm == 255.0
    assert snapshot.rim_in == AnalysisSettingsSnapshot.DEFAULTS["rim_in"]


def test_derivation_service_projects_active_car_snapshot() -> None:
    store = SettingsStore()
    created = store.add_car({"name": "Primary", "type": "coupe"})
    store.set_active_car(created.cars[0]["id"])
    service = SettingsDerivationService(
        active_car_aspects=store.active_car_aspects,
        active_car_snapshot=store.active_car_snapshot,
    )

    snapshot = service.active_car_snapshot()

    assert snapshot is not None
    assert snapshot.car_id == created.cars[0]["id"]
    assert snapshot.name == "Primary"
    assert snapshot.car_type == "coupe"
