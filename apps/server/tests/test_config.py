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
