"""Guard runtime speed-source synchronization between settings and the monitor."""

from __future__ import annotations

import pytest

from vibesensor.infra.config.speed_source_runtime import (
    SpeedSourceRuntimeApplier,
    SpeedSourceSettingsService,
)
from vibesensor.shared.types.speed_source_config import (
    SpeedSourceConfig,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
)


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


class _FakeSpeedSourceStore:
    def __init__(self) -> None:
        self._config = SpeedSourceConfig.default()

    def get_speed_source(self) -> SpeedSourcePayload:
        return self._config.to_dict()

    def preview_speed_source_update(self, data: SpeedSourceUpdatePayload) -> SpeedSourceConfig:
        return self._config.updated(data)

    def persist_speed_source(self, config: SpeedSourceConfig) -> SpeedSourceConfig:
        self._config = config.copy()
        return self._config.copy()

    def speed_source_config(self) -> SpeedSourceConfig:
        return self._config.copy()

    def update_speed_source(self, data: SpeedSourceUpdatePayload) -> SpeedSourcePayload:
        return self.persist_speed_source(self.preview_speed_source_update(data)).to_dict()


def test_runtime_applier_pushes_current_speed_source_to_monitor() -> None:
    store = _FakeSpeedSourceStore()
    monitor = _FakeSpeedSourceSync()
    store.update_speed_source(
        {
            "speedSource": "manual",
            "manualSpeedKph": 80,
            "staleTimeoutS": 17,
        }
    )

    SpeedSourceRuntimeApplier(speed_control=monitor).apply(store.speed_source_config())

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
    store = _FakeSpeedSourceStore()
    monitor = _FakeSpeedSourceSync()
    store.update_speed_source(
        {
            "speedSource": "obd2",
            "manualSpeedKph": 54,
            "staleTimeoutS": 12,
            "obdDeviceMac": "00043e5a4a4d",
            "obdDeviceName": "OBDLink MX+",
        }
    )

    SpeedSourceRuntimeApplier(speed_control=monitor).apply(store.speed_source_config())

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


def test_speed_source_service_updates_store_and_runtime() -> None:
    store = _FakeSpeedSourceStore()
    monitor = _FakeSpeedSourceSync()
    service = SpeedSourceSettingsService(
        settings_store=store,
        runtime_applier=SpeedSourceRuntimeApplier(speed_control=monitor),
    )

    result = service.update_speed_source({"speedSource": "manual", "manualSpeedKph": 42})

    assert result["speedSource"] == "manual"
    assert store.get_speed_source()["manualSpeedKph"] == pytest.approx(42.0)
    assert monitor.calls == [
        {
            "effective_speed_kmh": pytest.approx(42.0),
            "manual_source_selected": True,
            "stale_timeout_s": pytest.approx(10.0),
            "selected_source": "manual",
            "obd_device_mac": None,
            "obd_device_name": None,
        }
    ]
