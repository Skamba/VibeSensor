from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.config import PI_DIR, REPO_DIR, load_config


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_metrics_log_path_is_required(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"logging": {"metrics_log_path": ""}})
    with pytest.raises(ValueError, match="metrics_log_path must be configured"):
        load_config(config_path)


def test_metrics_log_path_resolves_relative(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        {"logging": {"metrics_log_path": "apps/server/data/new_metrics.jsonl"}},
    )
    cfg = load_config(config_path)
    assert cfg.logging.metrics_log_path == (REPO_DIR / "apps/server/data/new_metrics.jsonl")


def test_dev_and_docker_configs_equivalent() -> None:
    """config.dev.yaml and config.docker.yaml must produce identical AppConfig."""
    dev_cfg = load_config(PI_DIR / "config.dev.yaml")
    docker_cfg = load_config(PI_DIR / "config.docker.yaml")
    # Compare all meaningful fields (config_path will differ)
    assert dev_cfg.logging.metrics_log_path == docker_cfg.logging.metrics_log_path
    assert dev_cfg.clients_json_path == docker_cfg.clients_json_path
    assert dev_cfg.server == docker_cfg.server
    assert dev_cfg.udp == docker_cfg.udp
    assert dev_cfg.processing == docker_cfg.processing
    assert dev_cfg.gps == docker_cfg.gps
    assert dev_cfg.ap == docker_cfg.ap
