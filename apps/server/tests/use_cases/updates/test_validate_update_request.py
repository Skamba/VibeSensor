"""Tests for the standalone update-request validation helper."""

from __future__ import annotations

import pytest

from vibesensor.shared.exceptions import ConfigurationError
from vibesensor.use_cases.updates.models import validate_update_request


class TestValidateUpdateRequest:
    def test_valid_request(self) -> None:
        req = validate_update_request("TestNet", "pass123")
        assert req.ssid == "TestNet"
        assert req.password == "pass123"

    def test_strips_ssid_whitespace(self) -> None:
        req = validate_update_request("  MyNet  ", "pw")
        assert req.ssid == "MyNet"

    def test_empty_ssid_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="SSID"):
            validate_update_request("", "pw")

    def test_whitespace_only_ssid_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="SSID"):
            validate_update_request("   ", "pw")

    def test_ssid_too_long_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="SSID"):
            validate_update_request("x" * 65, "pw")

    def test_ssid_at_max_length_accepted(self) -> None:
        req = validate_update_request("x" * 64, "pw")
        assert len(req.ssid) == 64

    def test_password_too_long_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="Password"):
            validate_update_request("Net", "p" * 129)

    def test_password_at_max_length_accepted(self) -> None:
        req = validate_update_request("Net", "p" * 128)
        assert len(req.password) == 128

    def test_empty_password_accepted(self) -> None:
        req = validate_update_request("OpenNet", "")
        assert req.password == ""
