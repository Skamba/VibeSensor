"""Tests for typed config dataclass validation (ports and tracing round-trip)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.app.config_schema import (
    ServerConfig,
    TracingConfig,
    UDPConfig,
)


class TestServerConfigValidation:
    """ServerConfig.port must be 1–65535."""

    def test_valid_port(self) -> None:
        cfg = ServerConfig(host="0.0.0.0", port=8000)
        assert cfg.port == 8000

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 100_000])
    def test_invalid_port_rejected(self, bad_port: int) -> None:
        with pytest.raises(ValueError, match="port"):
            ServerConfig(host="0.0.0.0", port=bad_port)

    def test_boundary_ports_accepted(self) -> None:
        assert ServerConfig(host="0.0.0.0", port=1).port == 1
        assert ServerConfig(host="0.0.0.0", port=65535).port == 65535


class TestUDPConfigValidation:
    """UDPConfig port validation."""

    def test_valid_config(self) -> None:
        cfg = UDPConfig(
            data_host="0.0.0.0",
            data_port=9000,
            control_host="0.0.0.0",
            control_port=9001,
        )
        assert cfg.data_port == 9000

    @pytest.mark.parametrize("field", ["data_port", "control_port"])
    @pytest.mark.parametrize("bad_value", [0, -1, 65536])
    def test_invalid_port_rejected(self, field: str, bad_value: int) -> None:
        kwargs: dict[str, str | int] = {
            "data_host": "0.0.0.0",
            "data_port": 9000,
            "control_host": "0.0.0.0",
            "control_port": 9001,
        }
        kwargs[field] = bad_value
        with pytest.raises(ValueError, match=field):
            UDPConfig(**kwargs)  # type: ignore[arg-type]


class TestTracingConfigValidation:
    """TracingConfig stores the enabled flag and resolved output path."""

    def test_tracing_config_round_trip(self) -> None:
        cfg = TracingConfig(enabled=True, output_path=Path("/tmp/traces.jsonl"))
        assert cfg.enabled is True
        assert cfg.output_path == Path("/tmp/traces.jsonl")
