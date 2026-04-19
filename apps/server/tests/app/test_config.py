"""Config-loader coverage for deep merge, path resolution, and AP self-heal defaults."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.app.settings import SERVER_DIR, AppConfig, load_config


def _write_config(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_and_load(path: Path, payload: dict[str, object]) -> AppConfig:
    """Write YAML payload and return loaded config."""
    _write_config(path, payload)
    return load_config(path)


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    """Shared config file path for write/load tests."""
    return tmp_path / "config.yaml"


def test_logging_flags_allow_db_only_mode(cfg_path: Path) -> None:
    cfg = _write_and_load(
        cfg_path,
        {
            "logging": {
                "persist_history_db": True,
                "history_db_path": "db/history.db",
                "app_log_path": "logs/app.log",
            }
        },
    )

    assert cfg.logging.persist_history_db is True
    assert cfg.logging.history_db_path == cfg_path.parent / "db/history.db"
    assert cfg.logging.app_log_path == cfg_path.parent / "logs/app.log"
    assert cfg.logging.no_data_timeout_s == 15.0
    assert cfg.logging.run_retention_days == 7


@pytest.mark.parametrize(
    ("override", "field", "expected"),
    [
        pytest.param({}, "no_data_timeout_s", 15.0, id="no-data-timeout-default"),
        pytest.param(
            {"logging": {"no_data_timeout_s": 30}},
            "no_data_timeout_s",
            30.0,
            id="no-data-timeout-override",
        ),
        pytest.param({}, "run_retention_days", 7, id="run-retention-default"),
        pytest.param(
            {"logging": {"run_retention_days": 21}},
            "run_retention_days",
            21,
            id="run-retention-override",
        ),
    ],
)
def test_logging_defaults_and_overrides(
    cfg_path: Path,
    override: dict[str, object],
    field: str,
    expected: float | int,
) -> None:
    cfg = _write_and_load(cfg_path, override)
    assert getattr(cfg.logging, field) == expected


def test_base_dev_and_docker_configs_capture_intended_runtime_invariants(tmp_path: Path) -> None:
    base_cfg = _write_and_load(tmp_path / "config.yaml", {})
    dev_cfg = load_config(SERVER_DIR / "config.dev.yaml")
    docker_cfg = load_config(SERVER_DIR / "config.docker.yaml")

    assert base_cfg.server.host == dev_cfg.server.host == docker_cfg.server.host
    assert base_cfg.server.port == 80
    assert dev_cfg.server.port == docker_cfg.server.port == 8000
    assert base_cfg.udp == dev_cfg.udp == docker_cfg.udp
    assert base_cfg.processing == dev_cfg.processing == docker_cfg.processing
    assert base_cfg.logging.persist_history_db is True
    assert dev_cfg.logging.persist_history_db is True
    assert docker_cfg.logging.persist_history_db is True
    assert base_cfg.gps.gps_enabled is True
    assert dev_cfg.gps.gps_enabled is False
    assert docker_cfg.gps.gps_enabled is False
    assert base_cfg.ap.self_heal.enabled is True
    assert dev_cfg.ap.self_heal.enabled is True
    assert docker_cfg.ap.self_heal.enabled is False
    assert docker_cfg.update.rollback_dir != base_cfg.update.rollback_dir


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (4096, 4096),
        (0, 1),
        (-5, 1),
        ("512", 512),
        (1_000_000, 1_000_000),
    ],
)
def test_udp_data_queue_maxsize_loader_clamps_or_preserves_integer_like_values(
    cfg_path: Path,
    raw_value: object,
    expected: int,
) -> None:
    cfg = _write_and_load(cfg_path, {"udp": {"data_queue_maxsize": raw_value}})
    assert cfg.udp.data_queue_maxsize == expected


@pytest.mark.parametrize(
    ("raw_value", "message"),
    [
        (True, "udp.data_queue_maxsize"),
        ("not-a-number", "invalid literal for int()"),
    ],
)
def test_udp_data_queue_maxsize_rejects_non_integer_like_values(
    cfg_path: Path,
    raw_value: object,
    message: str,
) -> None:
    _write_config(cfg_path, {"udp": {"data_queue_maxsize": raw_value}})
    with pytest.raises(ValueError, match=message):
        load_config(cfg_path)


# --- AP WiFi channel validation ---


@pytest.mark.parametrize("channel", [1, 6, 7, 11, 14])
def test_ap_channel_valid_values_accepted(cfg_path: Path, channel: int) -> None:
    cfg = _write_and_load(cfg_path, {"ap": {"channel": channel}})
    assert cfg.ap.channel == channel


@pytest.mark.parametrize("channel", [0, -1, 15, 200, 36, 100])
def test_ap_channel_invalid_values_rejected(cfg_path: Path, channel: int) -> None:
    _write_config(cfg_path, {"ap": {"channel": channel}})
    with pytest.raises(ValueError, match="ap.channel must be 1-14"):
        load_config(cfg_path)


# --- server.port validation ---


@pytest.mark.parametrize("port", [1, 80, 443, 8000, 8080, 65535])
def test_server_port_valid_values_accepted(cfg_path: Path, port: int) -> None:
    cfg = _write_and_load(cfg_path, {"server": {"port": port}})
    assert cfg.server.port == port


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_server_port_invalid_values_rejected(cfg_path: Path, port: int) -> None:
    _write_config(cfg_path, {"server": {"port": port}})
    with pytest.raises(ValueError, match="server.port must be 1-65535"):
        load_config(cfg_path)


# --- ap.ip validation ---


@pytest.mark.parametrize(
    "ip",
    ["10.4.0.1/24", "192.168.1.1/24", "10.0.0.1", "172.16.0.1/16"],
)
def test_ap_ip_valid_values_accepted(cfg_path: Path, ip: str) -> None:
    cfg = _write_and_load(cfg_path, {"ap": {"ip": ip}})
    assert cfg.ap.ip == ip


@pytest.mark.parametrize(
    "ip",
    ["not-an-ip", "999.999.999.999", "10.4.0.1/99", "", "abc/24"],
)
def test_ap_ip_invalid_values_rejected(cfg_path: Path, ip: str) -> None:
    _write_config(cfg_path, {"ap": {"ip": ip}})
    with pytest.raises(ValueError, match="ap.ip must be a valid IPv4 address or CIDR"):
        load_config(cfg_path)
