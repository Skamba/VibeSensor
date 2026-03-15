from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.app.settings import SERVER_DIR, load_config


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_and_load(path: Path, payload: dict):
    """Write YAML payload and return loaded config."""
    _write_config(path, payload)
    return load_config(path)


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    """Shared config file path for write/load tests."""
    return tmp_path / "config.yaml"


def test_metrics_can_be_disabled(cfg_path: Path) -> None:
    cfg = _write_and_load(cfg_path, {"logging": {"log_metrics": False}})
    assert cfg.logging.log_metrics is False


def test_logging_flags_allow_db_only_mode(cfg_path: Path) -> None:
    cfg = _write_and_load(cfg_path, {"logging": {"persist_history_db": True}})
    assert cfg.logging.persist_history_db is True


def test_logging_no_data_timeout_defaults_and_allows_override(cfg_path: Path) -> None:
    cfg = _write_and_load(cfg_path, {})
    assert cfg.logging.no_data_timeout_s == 15.0

    cfg = _write_and_load(cfg_path, {"logging": {"no_data_timeout_s": 30}})
    assert cfg.logging.no_data_timeout_s == 30.0


def test_dev_and_docker_configs_equivalent() -> None:
    """config.dev.yaml and config.docker.yaml share core settings but Docker
    intentionally overrides environment-specific options (GPS disabled because
    Docker containers have no gpsd, AP self-heal disabled because nmcli/hostapd
    are absent, rollback_dir uses a container-local path).
    """
    dev_cfg = load_config(SERVER_DIR / "config.dev.yaml")
    docker_cfg = load_config(SERVER_DIR / "config.docker.yaml")
    # Core transport and processing settings must still agree
    assert dev_cfg.server == docker_cfg.server
    assert dev_cfg.udp == docker_cfg.udp
    assert dev_cfg.processing == docker_cfg.processing
    # GPS: Docker container has no gpsd — GPS is intentionally disabled there
    assert dev_cfg.gps.gpsd_host == docker_cfg.gps.gpsd_host
    assert dev_cfg.gps.gpsd_port == docker_cfg.gps.gpsd_port
    assert docker_cfg.gps.gps_enabled is False, "Docker config must disable GPS"
    # AP: self-heal is intentionally disabled in Docker (no nmcli/hostapd)
    assert docker_cfg.ap.self_heal.enabled is False, "Docker config must disable AP self-heal"


def test_default_server_port_is_80_for_base_config(cfg_path: Path) -> None:
    cfg = _write_and_load(cfg_path, {})
    assert cfg.server.port == 80


def test_dev_and_docker_override_server_port_to_8000() -> None:
    dev_cfg = load_config(SERVER_DIR / "config.dev.yaml")
    docker_cfg = load_config(SERVER_DIR / "config.docker.yaml")
    assert dev_cfg.server.port == 8000
    assert docker_cfg.server.port == 8000


def test_udp_data_queue_maxsize_override_and_clamp(cfg_path: Path) -> None:
    cfg = _write_and_load(cfg_path, {"udp": {"data_queue_maxsize": 4096}})
    assert cfg.udp.data_queue_maxsize == 4096

    cfg = _write_and_load(cfg_path, {"udp": {"data_queue_maxsize": 0}})
    assert cfg.udp.data_queue_maxsize == 1


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
