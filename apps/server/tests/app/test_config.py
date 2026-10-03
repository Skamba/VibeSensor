"""Config-loader coverage for deep merge, path resolution, and legacy-key tolerance."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.app.config_loader import load_config
from vibesensor.app.config_paths import SERVER_DIR
from vibesensor.app.config_schema import AppConfig


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


def test_logging_paths_resolve_relative_to_config(cfg_path: Path) -> None:
    cfg = _write_and_load(
        cfg_path,
        {
            "logging": {
                "history_db_path": "db/history.db",
                "app_log_path": "logs/app.log",
            }
        },
    )

    assert cfg.logging.history_db_path == cfg_path.parent / "db/history.db"
    assert cfg.logging.app_log_path == cfg_path.parent / "logs/app.log"


def test_app_log_path_null_disables_file_logging(cfg_path: Path) -> None:
    cfg = _write_and_load(cfg_path, {"logging": {"app_log_path": None}})
    assert cfg.logging.app_log_path is None


def test_legacy_device_config_with_removed_keys_still_loads(
    cfg_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Device configs written by older releases keep loading; removed knobs are ignored."""
    legacy = {
        "ap": {
            "ssid": "Workshop",
            "psk": "secret-psk",
            "ip": "10.9.0.1/24",
            "channel": 11,
            "ifname": "wlan1",
            "con_name": "Old-AP",
            "self_heal": {
                "enabled": False,
                "diagnostics_lookback_minutes": 9,
                "min_restart_interval_seconds": 60,
                "state_file": "state/self-heal.json",
            },
        },
        "udp": {"data_port": 9100, "data_queue_maxsize": 2048},
        "processing": {
            "sample_rate_hz": 1600,
            "waveform_seconds": 4,
            "client_live_ttl_seconds": 5,
            "client_ttl_seconds": 60,
            "accel_scale_g_per_lsb": None,
        },
        "logging": {
            "history_db_path": "db/history.db",
            "metrics_log_hz": 2,
            "no_data_timeout_s": 30,
            "persist_history_db": True,
            "run_retention_days": 30,
            "raw_capture_retention_days": 7,
            "shutdown_analysis_timeout_s": 10,
        },
        "gps": {"gps_enabled": False, "gpsd_host": "127.0.0.1", "gpsd_port": 2947},
        "tracing": {"enabled": True, "output_path": "data/traces.jsonl"},
    }

    with caplog.at_level("WARNING", logger="vibesensor.app.settings"):
        cfg = _write_and_load(cfg_path, legacy)

    assert cfg.ap.ssid == "Workshop"
    assert cfg.ap.psk == "secret-psk"
    assert cfg.udp.data_port == 9100
    assert cfg.logging.history_db_path == cfg_path.parent / "db/history.db"
    assert cfg.gps.gps_enabled is False
    warned = caplog.text
    for key in (
        "ap.ip",
        "ap.self_heal",
        "udp.data_queue_maxsize",
        "processing",
        "logging.run_retention_days",
        "gps.gpsd_port",
        "tracing",
    ):
        assert f"Ignoring unsupported config key {key}\n" in warned + "\n"


def test_base_dev_and_docker_configs_capture_intended_runtime_invariants(tmp_path: Path) -> None:
    base_cfg = _write_and_load(tmp_path / "config.yaml", {})
    dev_cfg = load_config(SERVER_DIR / "config.dev.yaml")
    docker_cfg = load_config(SERVER_DIR / "config.docker.yaml")
    pi_cfg = load_config(SERVER_DIR / "config.pi.yaml")

    assert base_cfg.server.host == dev_cfg.server.host == docker_cfg.server.host
    assert base_cfg.server.port == 80
    assert dev_cfg.server.port == docker_cfg.server.port == 8000
    assert base_cfg.udp == dev_cfg.udp == docker_cfg.udp
    assert base_cfg.gps.gps_enabled is True
    assert dev_cfg.gps.gps_enabled is False
    assert docker_cfg.gps.gps_enabled is False
    assert pi_cfg.logging.history_db_path == Path("/var/lib/vibesensor/history.db")
    assert base_cfg.update.rollback_dir == Path("/var/lib/vibesensor/rollback")
    assert pi_cfg.update.rollback_dir == Path("/var/lib/vibesensor/rollback")
    assert dev_cfg.update.rollback_dir == SERVER_DIR / "data/rollback"
    assert docker_cfg.update.rollback_dir != base_cfg.update.rollback_dir


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
