"""Additional config coverage for logging defaults and network validation edges."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.app.config_loader import _read_config_file, _resolve_config_path
from vibesensor.app.settings import load_config
from vibesensor.shared.json_utils import deep_merge as _deep_merge

# -- _deep_merge ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "override", "expected"),
    [
        ({"a": 1, "b": 2}, {"a": 10}, {"a": 10, "b": 2}),
        ({"top": {"a": 1, "b": 2}}, {"top": {"b": 3}}, {"top": {"a": 1, "b": 3}}),
        ({"a": 1}, {"b": 2}, {"a": 1, "b": 2}),
        ({"items": [1, 2]}, {"items": [3]}, {"items": [3]}),
    ],
)
def test_deep_merge_contract(
    base: dict[str, object],
    override: dict[str, object],
    expected: dict[str, object],
) -> None:
    assert _deep_merge(base, override) == expected


def test_deep_merge_null_dict_section_keeps_defaults_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    result = _deep_merge({"ap": {"self_heal": {"enabled": True}}}, {"ap": None})

    assert result == {"ap": {"self_heal": {"enabled": True}}}
    assert "keeping default section" in caplog.text


# -- _resolve_config_path ------------------------------------------------------


def test_resolve_config_path_absolute(tmp_path: Path) -> None:
    result = _resolve_config_path("/tmp/foo.txt", tmp_path / "config.yaml")
    assert result == Path("/tmp/foo.txt")


def test_resolve_config_path_relative(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    result = _resolve_config_path("data/foo.txt", config_path)
    assert result == (tmp_path / "data/foo.txt")


def test_resolve_config_path_preserves_parent_traversal_relative_to_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs" / "dev"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"

    result = _resolve_config_path("../shared/state.json", config_path)

    assert result.resolve() == (config_dir.parent / "shared/state.json").resolve()


def test_resolve_config_path_uses_real_config_parent_for_symlinks(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real_config = real_dir / "config.yaml"
    real_config.write_text("{}", encoding="utf-8")
    link_dir = tmp_path / "linked"
    link_dir.mkdir()
    symlink_path = link_dir / "config.yaml"
    symlink_path.symlink_to(real_config)

    result = _resolve_config_path("data/file.txt", symlink_path)

    assert result.resolve() == (real_dir / "data/file.txt").resolve()


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
    with pytest.raises(ValueError, match="must contain a YAML object"):
        _read_config_file(cfg_path)


# -- load_config: AP self-heal -------------------------------------------------
# NOTE: accel_scale_g_per_lsb zero/negative tests live in
# test_config_validation.py::TestAccelScaleValidation.


def _write_config(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


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
