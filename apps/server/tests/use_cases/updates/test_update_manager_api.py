from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from vibesensor.adapters.http.dependencies import (
    HistoryDeps,
    RouterDeps,
    SettingsDeps,
    TelemetryDeps,
    UpdateDeps,
)
from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import UpdateTransport
from vibesensor.use_cases.updates.runtime import build_update_manager_runtime
from vibesensor.use_cases.updates.status import UpdateStateStore


class TestUpdateApiEndpoints:
    def test_status_endpoint_exists(self, tmp_path) -> None:
        from vibesensor.adapters.http import create_router

        placeholder = MagicMock()
        state = RouterDeps(
            telemetry=TelemetryDeps(
                processing_loop_state=placeholder,
                health_state=placeholder,
                processor=placeholder,
                registry=placeholder,
                control_plane=placeholder,
                run_recorder=placeholder,
                ws_hub=placeholder,
            ),
            settings=SettingsDeps(
                settings_store=placeholder,
                speed_source_service=placeholder,
                gps_monitor=placeholder,
            ),
            history=HistoryDeps(
                run_service=placeholder,
                report_service=placeholder,
                export_service=placeholder,
            ),
            updates=UpdateDeps(
                update_manager=UpdateManager(
                    runtime=build_update_manager_runtime(
                        state_store=UpdateStateStore(tmp_path / "update_status.json"),
                    ),
                ),
                esp_flash_manager=MagicMock(),
            ),
        )
        router = create_router(state)
        paths = [route.path for route in router.routes]
        assert "/api/update/status" in paths
        assert "/api/update/internet-status" in paths
        assert "/api/update/start" in paths
        assert "/api/update/cancel" in paths

    def test_start_request_model_validation(self) -> None:
        from vibesensor.adapters.http.models import UpdateStartRequest

        req = UpdateStartRequest(ssid="TestNet", password="pass123")
        assert req.ssid == "TestNet"
        with pytest.raises(ValidationError, match=r"ssid"):
            UpdateStartRequest(ssid="", password="pass")
        with pytest.raises(ValidationError, match=r"ssid"):
            UpdateStartRequest(ssid="x" * 65, password="pass")
        with pytest.raises(ValidationError, match=r"password"):
            UpdateStartRequest(ssid="Net", password="x" * 129)
        req = UpdateStartRequest(ssid="OpenNet")
        assert req.password == ""
        req = UpdateStartRequest(transport=UpdateTransport.usb_internet)
        assert req.transport == UpdateTransport.usb_internet
        assert req.ssid is None
        assert req.password == ""
        with pytest.raises(ValidationError, match=r"ssid"):
            UpdateStartRequest(transport=UpdateTransport.usb_internet, ssid="OpenNet")
        with pytest.raises(ValidationError, match=r"password"):
            UpdateStartRequest(transport=UpdateTransport.usb_internet, password="secret")
