from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from vibesensor.update.manager import UpdateManager


class TestUpdateApiEndpoints:
    def test_status_endpoint_exists(self) -> None:
        from vibesensor.routes import create_router

        state = MagicMock()
        state.update_manager = UpdateManager()
        state.esp_flash_manager = MagicMock()
        router = create_router(state)
        paths = [route.path for route in router.routes]
        assert "/api/update/status" in paths
        assert "/api/update/start" in paths
        assert "/api/update/cancel" in paths

    def test_start_request_model_validation(self) -> None:
        from vibesensor.api_models import UpdateStartRequest

        req = UpdateStartRequest(ssid="TestNet", password="pass123")
        assert req.ssid == "TestNet"
        with pytest.raises(ValidationError):
            UpdateStartRequest(ssid="", password="pass")
        with pytest.raises(ValidationError):
            UpdateStartRequest(ssid="x" * 65, password="pass")
        with pytest.raises(ValidationError):
            UpdateStartRequest(ssid="Net", password="x" * 129)
        req = UpdateStartRequest(ssid="OpenNet")
        assert req.password == ""
