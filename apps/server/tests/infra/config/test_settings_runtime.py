from __future__ import annotations

import pytest

from vibesensor.infra.config.settings_runtime import SettingsRuntimeApplier
from vibesensor.infra.config.settings_store import SettingsStore


class _FakeSpeedSourceSync:
    def __init__(self) -> None:
        self.calls: list[tuple[float | None, bool, float | None]] = []

    def apply_speed_source_settings(
        self,
        *,
        effective_speed_kmh: float | None,
        manual_source_selected: bool,
        stale_timeout_s: float | None = None,
    ) -> float | None:
        self.calls.append((effective_speed_kmh, manual_source_selected, stale_timeout_s))
        return effective_speed_kmh


def test_runtime_applier_pushes_current_speed_source_to_monitor() -> None:
    store = SettingsStore()
    monitor = _FakeSpeedSourceSync()
    applier = SettingsRuntimeApplier(
        gps_monitor=monitor,
        speed_source_reader=store,
    )
    store.update_speed_source(
        {
            "speedSource": "manual",
            "manualSpeedKph": 80,
            "staleTimeoutS": 17,
        }
    )

    applier.sync_all()

    assert monitor.calls == [(pytest.approx(80.0), True, pytest.approx(17.0))]


def test_store_invokes_bound_speed_source_sync_after_persist() -> None:
    store = SettingsStore()
    calls: list[str] = []
    store.bind_speed_source_sync(lambda: calls.append("apply"))

    store.update_speed_source({"speedSource": "manual", "manualSpeedKph": 42})

    assert calls == ["apply"]
