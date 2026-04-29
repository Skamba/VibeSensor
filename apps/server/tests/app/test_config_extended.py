"""Additional config coverage for public loader path and validation behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.app.config_loader import load_config


def _write_config(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_config_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_config_preserves_absolute_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        {
            "logging": {
                "history_db_path": "/tmp/history.db",
                "app_log_path": "/tmp/app.log",
            },
            "tracing": {
                "enabled": True,
                "output_path": "/tmp/traces.jsonl",
            },
            "ap": {
                "self_heal": {
                    "state_file": "/tmp/hotspot-state.json",
                }
            },
            "update": {
                "rollback_dir": "/tmp/rollback",
            },
        },
    )

    result = load_config(config_path)

    assert result.logging.history_db_path == Path("/tmp/history.db")
    assert result.logging.app_log_path == Path("/tmp/app.log")
    assert result.tracing.output_path == Path("/tmp/traces.jsonl")
    assert result.ap.self_heal.state_file == Path("/tmp/hotspot-state.json")
    assert result.update.rollback_dir == Path("/tmp/rollback")


def test_load_config_resolves_relative_paths_from_config_parent(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "config.yaml"
    _write_config(
        config_path,
        {
            "logging": {
                "history_db_path": "data/history.db",
                "app_log_path": "logs/app.log",
            },
            "tracing": {
                "enabled": True,
                "output_path": "logs/traces.jsonl",
            },
            "ap": {
                "self_heal": {
                    "state_file": "data/hotspot-state.json",
                }
            },
            "update": {
                "rollback_dir": "data/rollback",
            },
        },
    )

    result = load_config(config_path)

    assert result.logging.history_db_path == config_path.parent / "data/history.db"
    assert result.logging.app_log_path == config_path.parent / "logs/app.log"
    assert result.tracing.output_path == config_path.parent / "logs/traces.jsonl"
    assert result.ap.self_heal.state_file == config_path.parent / "data/hotspot-state.json"
    assert result.update.rollback_dir == config_path.parent / "data/rollback"


def test_load_config_preserves_parent_traversal_relative_to_config(tmp_path: Path) -> None:
    config_path = tmp_path / "configs" / "dev" / "config.yaml"
    _write_config(config_path, {"logging": {"history_db_path": "../shared/history.db"}})

    result = load_config(config_path)

    assert (
        result.logging.history_db_path.resolve()
        == (tmp_path / "configs" / "shared" / "history.db").resolve()
    )


def test_load_config_uses_real_config_parent_for_symlinks(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_config = real_dir / "config.yaml"
    _write_config(real_config, {"logging": {"history_db_path": "data/history.db"}})
    link_dir = tmp_path / "linked"
    link_dir.mkdir()
    symlink_path = link_dir / "config.yaml"
    symlink_path.symlink_to(real_config)

    result = load_config(symlink_path)

    assert result.logging.history_db_path.resolve() == (real_dir / "data/history.db").resolve()


def test_load_config_missing_explicit_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Explicitly specified config file does not exist"):
        load_config(tmp_path / "missing.yaml")


def test_load_config_invalid_yaml_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config_text(config_path, "server: [\n")

    with pytest.raises(ValueError, match="contains invalid YAML"):
        load_config(config_path)


def test_load_config_non_dict_top_level_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config_text(config_path, "- item1\n- item2\n")

    with pytest.raises(ValueError, match="must contain a YAML object"):
        load_config(config_path)


def test_load_config_null_section_keeps_defaults_and_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {"ap": None})

    with caplog.at_level("WARNING", logger="vibesensor.shared.json_utils"):
        result = load_config(config_path)

    assert result.ap.self_heal.enabled is True
    assert "keeping default section" in caplog.text


def test_load_config_ap_self_heal_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, {})

    result = load_config(config_path)

    assert result.ap.self_heal.enabled is True
    assert result.ap.self_heal.diagnostics_lookback_minutes == 5
    assert result.ap.self_heal.min_restart_interval_seconds == 120
    assert result.ap.self_heal.state_file == tmp_path / "data/hotspot-self-heal-state.json"


def test_load_config_ap_self_heal_override(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        {
            "ap": {
                "self_heal": {
                    "enabled": True,
                    "diagnostics_lookback_minutes": 7,
                    "min_restart_interval_seconds": 240,
                    "state_file": "/tmp/hotspot-heal-state.json",
                },
            },
        },
    )

    result = load_config(config_path)

    assert result.ap.self_heal.diagnostics_lookback_minutes == 7
    assert result.ap.self_heal.min_restart_interval_seconds == 240
    assert result.ap.self_heal.state_file == Path("/tmp/hotspot-heal-state.json")
