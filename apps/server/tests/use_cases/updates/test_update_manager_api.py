from __future__ import annotations

import pytest
from pydantic import ValidationError

from vibesensor.use_cases.updates.models import UpdateTransport


class TestUpdateApiEndpoints:
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
