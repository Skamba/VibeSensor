from __future__ import annotations

from pathlib import Path

import yaml

from vibesensor.config import REPO_DIR, load_config


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_legacy_metrics_csv_path_is_still_supported(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        {
            "logging": {
                "metrics_csv_path": "pi/data/legacy_metrics.jsonl",
            }
        },
    )

    cfg = load_config(config_path)

    assert cfg.logging.metrics_log_path == (REPO_DIR / "pi/data/legacy_metrics.jsonl")
    assert cfg.logging.metrics_csv_path == cfg.logging.metrics_log_path


def test_metrics_log_path_takes_precedence_over_legacy_key(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        {
            "logging": {
                "metrics_csv_path": "pi/data/legacy_metrics.jsonl",
                "metrics_log_path": "pi/data/new_metrics.jsonl",
            }
        },
    )

    cfg = load_config(config_path)

    assert cfg.logging.metrics_log_path == (REPO_DIR / "pi/data/new_metrics.jsonl")
