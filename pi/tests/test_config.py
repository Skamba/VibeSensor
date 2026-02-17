from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.config import REPO_DIR, load_config


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
        {"logging": {"metrics_log_path": "pi/data/new_metrics.jsonl"}},
    )
    cfg = load_config(config_path)
    assert cfg.logging.metrics_log_path == (REPO_DIR / "pi/data/new_metrics.jsonl")
