from __future__ import annotations

import sys
from pathlib import Path

import yaml
from _paths import SERVER_ROOT

from vibesensor.shared.subprocess_server import (
    build_isolated_server_config,
    build_isolated_server_env,
    build_server_subprocess_cmd,
)


def test_build_isolated_server_config_rewrites_runtime_paths_and_copies_seed_data(
    tmp_path: Path,
) -> None:
    seed_dir = tmp_path / "seed-data"
    seed_dir.mkdir()
    (seed_dir / "car_library.json").write_text('{"cars":[]}\n', encoding="utf-8")
    runtime_root = tmp_path / "runtime"

    result = build_isolated_server_config(
        SERVER_ROOT / "config.docker.yaml",
        runtime_root,
        host="127.0.0.1",
        port=18080,
        udp_data_port=19080,
        udp_control_port=19180,
        config_name="shard.yaml",
        data_seed_dir=seed_dir,
    )

    assert result.root == runtime_root
    assert result.config_path == runtime_root / "shard.yaml"
    assert (result.data_dir / "car_library.json").read_text(encoding="utf-8") == '{"cars":[]}\n'

    data = yaml.safe_load(result.config_path.read_text(encoding="utf-8"))
    assert data["server"] == {"host": "127.0.0.1", "port": 18080}
    assert data["udp"] == {
        "data_host": "127.0.0.1",
        "data_port": 19080,
        "control_host": "127.0.0.1",
        "control_port": 19180,
    }
    assert data["gps"]["gps_enabled"] is False
    assert data["ap"]["self_heal"]["enabled"] is False
    assert data["logging"]["history_db_path"].endswith("history.db")
    assert data["logging"]["app_log_path"].endswith("app.log")
    assert data["update"]["rollback_dir"].endswith("rollback")


def test_build_isolated_server_env_sets_runtime_paths(tmp_path: Path) -> None:
    env = build_isolated_server_env(
        tmp_path,
        repo_root=SERVER_ROOT.parent.parent,
        extra_env={"VIBESENSOR_SERVE_STATIC": "0", "CUSTOM_FLAG": "1"},
    )

    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["VIBESENSOR_UPDATE_STATE_PATH"].endswith("data/update_status.json")
    assert env["VIBESENSOR_FIRMWARE_CACHE_DIR"].endswith("firmware")
    assert env["VIBESENSOR_ROLLBACK_DIR"].endswith("rollback")
    assert env["VIBESENSOR_REPO_PATH"] == str(SERVER_ROOT.parent.parent)
    assert env["VIBESENSOR_SERVE_STATIC"] == "0"
    assert env["CUSTOM_FLAG"] == "1"


def test_build_server_subprocess_cmd_uses_embedded_bootstrap(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"

    cmd = build_server_subprocess_cmd(config_path)

    assert cmd[:2] == [sys.executable, "-c"]
    assert "from vibesensor.app import create_app" in cmd[2]
    assert "loop='asyncio'" in cmd[2]
    assert cmd[3] == str(config_path)
