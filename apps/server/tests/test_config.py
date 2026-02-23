from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.config import SERVER_DIR, load_config


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_metrics_log_path_required_when_metrics_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"logging": {"log_metrics": True, "metrics_log_path": ""}})
    with pytest.raises(
        ValueError, match="metrics_log_path must be configured when log_metrics is true"
    ):
        load_config(config_path)


def test_metrics_log_path_resolves_relative_to_config_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"logging": {"metrics_log_path": "new_metrics.jsonl"}})
    cfg = load_config(config_path)
    assert cfg.logging.metrics_log_path == (tmp_path / "new_metrics.jsonl")


def test_metrics_log_path_not_required_when_metrics_disabled(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"logging": {"log_metrics": False, "metrics_log_path": ""}})
    cfg = load_config(config_path)
    assert cfg.logging.log_metrics is False


def test_logging_flags_allow_db_only_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        {"logging": {"persist_history_db": True}},
    )
    cfg = load_config(config_path)
    assert cfg.logging.persist_history_db is True


def test_dev_and_docker_configs_equivalent() -> None:
    """config.dev.yaml and config.docker.yaml must produce identical AppConfig."""
    dev_cfg = load_config(SERVER_DIR / "config.dev.yaml")
    docker_cfg = load_config(SERVER_DIR / "config.docker.yaml")
    # Compare all meaningful fields (config_path will differ)
    assert dev_cfg.logging.metrics_log_path == docker_cfg.logging.metrics_log_path
    assert dev_cfg.server == docker_cfg.server
    assert dev_cfg.udp == docker_cfg.udp
    assert dev_cfg.processing == docker_cfg.processing
    assert dev_cfg.gps == docker_cfg.gps
    assert dev_cfg.ap == docker_cfg.ap


def test_default_server_port_is_80_for_base_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {})
    cfg = load_config(config_path)
    assert cfg.server.port == 80


def test_dev_and_docker_override_server_port_to_8000() -> None:
    dev_cfg = load_config(SERVER_DIR / "config.dev.yaml")
    docker_cfg = load_config(SERVER_DIR / "config.docker.yaml")
    assert dev_cfg.server.port == 8000
    assert docker_cfg.server.port == 8000


def test_udp_data_queue_maxsize_override_and_clamp(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"udp": {"data_queue_maxsize": 4096}})
    cfg = load_config(config_path)
    assert cfg.udp.data_queue_maxsize == 4096

    _write_config(config_path, {"udp": {"data_queue_maxsize": 0}})
    cfg = load_config(config_path)
    assert cfg.udp.data_queue_maxsize == 1


# --- AP WiFi channel validation ---


@pytest.mark.parametrize("channel", [1, 6, 7, 11, 14])
def test_ap_channel_valid_values_accepted(tmp_path: Path, channel: int) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"ap": {"channel": channel}})
    cfg = load_config(config_path)
    assert cfg.ap.channel == channel


@pytest.mark.parametrize("channel", [0, -1, 15, 200, 36, 100])
def test_ap_channel_invalid_values_rejected(tmp_path: Path, channel: int) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"ap": {"channel": channel}})
    with pytest.raises(ValueError, match="ap.channel must be 1-14"):
        load_config(config_path)


# --- server.port validation ---


@pytest.mark.parametrize("port", [1, 80, 443, 8000, 8080, 65535])
def test_server_port_valid_values_accepted(tmp_path: Path, port: int) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"server": {"port": port}})
    cfg = load_config(config_path)
    assert cfg.server.port == port


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_server_port_invalid_values_rejected(tmp_path: Path, port: int) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"server": {"port": port}})
    with pytest.raises(ValueError, match="server.port must be 1-65535"):
        load_config(config_path)


# --- ap.ip validation ---


@pytest.mark.parametrize(
    "ip",
    ["10.4.0.1/24", "192.168.1.1/24", "10.0.0.1", "172.16.0.1/16"],
)
def test_ap_ip_valid_values_accepted(tmp_path: Path, ip: str) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"ap": {"ip": ip}})
    cfg = load_config(config_path)
    assert cfg.ap.ip == ip


@pytest.mark.parametrize(
    "ip",
    ["not-an-ip", "999.999.999.999", "10.4.0.1/99", "", "abc/24"],
)
def test_ap_ip_invalid_values_rejected(tmp_path: Path, ip: str) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"ap": {"ip": ip}})
    with pytest.raises(ValueError, match="ap.ip must be a valid IPv4 address or CIDR"):
        load_config(config_path)
