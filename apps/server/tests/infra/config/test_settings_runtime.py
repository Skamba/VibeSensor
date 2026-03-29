"""Guard runtime speed-source synchronization between settings and the monitor."""

from __future__ import annotations

import pytest

from vibesensor.infra.config.settings_runtime import SettingsRuntimeApplier
from vibesensor.infra.config.settings_store import SettingsStore


class _FakeSpeedSourceSync:
    def __init__(self) -> None:
        self.calls: list[dict[str, object | None]] = []

    def apply_speed_source_settings(
        self,
        *,
        effective_speed_kmh: float | None,
        manual_source_selected: bool,
        stale_timeout_s: float | None = None,
        selected_source=None,
        obd_device_mac: str | None = None,
        obd_device_name: str | None = None,
    ) -> float | None:
        self.calls.append(
            {
                "effective_speed_kmh": effective_speed_kmh,
                "manual_source_selected": manual_source_selected,
                "stale_timeout_s": stale_timeout_s,
                "selected_source": selected_source,
                "obd_device_mac": obd_device_mac,
                "obd_device_name": obd_device_name,
            }
        )
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

    assert monitor.calls == [
        {
            "effective_speed_kmh": pytest.approx(80.0),
            "manual_source_selected": True,
            "stale_timeout_s": pytest.approx(17.0),
            "selected_source": "manual",
            "obd_device_mac": None,
            "obd_device_name": None,
        }
    ]


def test_runtime_applier_keeps_live_source_manual_fallback_and_obd_device() -> None:
    store = SettingsStore()
    monitor = _FakeSpeedSourceSync()
    applier = SettingsRuntimeApplier(
        gps_monitor=monitor,
        speed_source_reader=store,
    )
    store.update_speed_source(
        {
            "speedSource": "obd2",
            "manualSpeedKph": 54,
            "staleTimeoutS": 12,
            "obdDeviceMac": "00043e5a4a4d",
            "obdDeviceName": "OBDLink MX+",
        }
    )

    applier.sync_all()

    assert monitor.calls == [
        {
            "effective_speed_kmh": pytest.approx(54.0),
            "manual_source_selected": False,
            "stale_timeout_s": pytest.approx(12.0),
            "selected_source": "obd2",
            "obd_device_mac": "00043e5a4a4d",
            "obd_device_name": "OBDLink MX+",
        }
    ]


def test_store_invokes_bound_speed_source_sync_after_persist() -> None:
    store = SettingsStore()
    calls: list[str] = []
    store.bind_speed_source_sync(lambda: calls.append("apply"))

    store.update_speed_source({"speedSource": "manual", "manualSpeedKph": 42})

    assert calls == ["apply"]
