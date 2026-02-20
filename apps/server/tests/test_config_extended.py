from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.config import (
    _deep_merge,
    _read_config_file,
    _resolve_config_path,
    _split_host_port,
    load_config,
)

# -- _split_host_port ---------------------------------------------------------


def test_split_host_port_valid() -> None:
    host, port = _split_host_port("0.0.0.0:9000")
    assert host == "0.0.0.0"
    assert port == 9000


def test_split_host_port_missing_colon_raises() -> None:
    with pytest.raises(ValueError):
        _split_host_port("localhost9000")


# -- _deep_merge ---------------------------------------------------------------


def test_deep_merge_overrides_scalar() -> None:
    base = {"a": 1, "b": 2}
    override = {"a": 10}
    result = _deep_merge(base, override)
    assert result["a"] == 10
    assert result["b"] == 2


def test_deep_merge_nested() -> None:
    base = {"top": {"a": 1, "b": 2}}
    override = {"top": {"b": 3}}
    result = _deep_merge(base, override)
    assert result["top"]["a"] == 1
    assert result["top"]["b"] == 3


def test_deep_merge_new_key() -> None:
    base = {"a": 1}
    override = {"b": 2}
    result = _deep_merge(base, override)
    assert result["a"] == 1
    assert result["b"] == 2


# -- _resolve_config_path ------------------------------------------------------


def test_resolve_config_path_absolute(tmp_path: Path) -> None:
    result = _resolve_config_path("/tmp/foo.txt", tmp_path / "config.yaml")
    assert result == Path("/tmp/foo.txt")


def test_resolve_config_path_relative(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    result = _resolve_config_path("data/foo.txt", config_path)
    assert result == (tmp_path / "data/foo.txt")


# -- _read_config_file ---------------------------------------------------------


def test_read_config_file_missing_returns_empty(tmp_path: Path) -> None:
    result = _read_config_file(tmp_path / "nonexistent.yaml")
    assert result == {}


def test_read_config_file_valid(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("ap:\n  ssid: TestNet\n")
    result = _read_config_file(cfg_path)
    assert result["ap"]["ssid"] == "TestNet"


def test_read_config_file_non_dict_raises(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("- item1\n- item2\n")
    with pytest.raises(ValueError):
        _read_config_file(cfg_path)


# -- load_config accel_scale negative ------------------------------------------


def test_load_config_negative_accel_scale(tmp_path: Path) -> None:
    cfg = {
        "processing": {"accel_scale_g_per_lsb": -1.0},
        "logging": {"metrics_log_path": "/tmp/test_metrics.jsonl"},
    }
    cfg_path = tmp_path / "config.yaml"
    with cfg_path.open("w") as f:
        yaml.safe_dump(cfg, f)
    result = load_config(cfg_path)
    assert result.processing.accel_scale_g_per_lsb is None


def test_load_config_ap_self_heal_defaults(tmp_path: Path) -> None:
    cfg = {
        "logging": {"metrics_log_path": "/tmp/test_metrics.jsonl"},
    }
    cfg_path = tmp_path / "config.yaml"
    with cfg_path.open("w") as f:
        yaml.safe_dump(cfg, f)

    result = load_config(cfg_path)

    assert result.ap.self_heal.enabled is True
    assert result.ap.self_heal.interval_seconds == 120
    assert result.ap.self_heal.allow_disable_resolved_stub_listener is False


def test_load_config_ap_self_heal_override(tmp_path: Path) -> None:
    cfg = {
        "logging": {"metrics_log_path": "/tmp/test_metrics.jsonl"},
        "ap": {
            "self_heal": {
                "enabled": True,
                "interval_seconds": 180,
                "diagnostics_lookback_minutes": 7,
                "min_restart_interval_seconds": 240,
                "allow_disable_resolved_stub_listener": True,
                "state_file": "/tmp/hotspot-heal-state.json",
            }
        },
    }
    cfg_path = tmp_path / "config.yaml"
    with cfg_path.open("w") as f:
        yaml.safe_dump(cfg, f)

    result = load_config(cfg_path)

    assert result.ap.self_heal.interval_seconds == 180
    assert result.ap.self_heal.diagnostics_lookback_minutes == 7
    assert result.ap.self_heal.min_restart_interval_seconds == 240
    assert result.ap.self_heal.allow_disable_resolved_stub_listener is True
    assert result.ap.self_heal.state_file == Path("/tmp/hotspot-heal-state.json")
