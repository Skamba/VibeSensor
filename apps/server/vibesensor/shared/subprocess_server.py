"""Helpers for isolated local server subprocess runs."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import yaml

__all__ = [
    "IsolatedRuntimePaths",
    "build_isolated_server_config",
    "build_isolated_server_env",
    "build_server_subprocess_cmd",
    "start_server_subprocess",
    "terminate_subprocess",
]


@dataclass(frozen=True)
class IsolatedRuntimePaths:
    root: Path
    data_dir: Path
    rollback_dir: Path
    config_path: Path


_SERVER_SUBPROCESS_BOOTSTRAP = "\n".join(
    [
        "from vibesensor.app.bootstrap import _run_server_with_port_fallback",
        "from vibesensor.app.config_loader import load_config",
        "from vibesensor.shared.process_settings import export_config_path_env",
        "import sys",
        "from pathlib import Path",
        "config_path = Path(sys.argv[1])",
        "config = load_config(config_path)",
        "export_config_path_env(config_path)",
        "_run_server_with_port_fallback(",
        "    'vibesensor.app.bootstrap:create_app_from_env',",
        "    host=config.server.host,",
        "    port=config.server.port,",
        "    factory=True,",
        ")",
    ],
)


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected config mapping in {path}")
    return data


def _mapping_section(root: dict[str, object], key: str) -> dict[str, object]:
    value = root.get(key)
    if value is None:
        section: dict[str, object] = {}
        root[key] = section
        return section
    if not isinstance(value, dict):
        raise ValueError(f"Expected config section {key!r} to be a mapping")
    return value


def build_isolated_server_config(
    source_config: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    udp_data_port: int,
    udp_control_port: int,
    config_name: str = "runtime.yaml",
    data_seed_dir: Path | None = None,
) -> IsolatedRuntimePaths:
    if udp_data_port > 65535 or udp_control_port > 65535:
        raise ValueError(
            f"UDP ports exceed range: data_port={udp_data_port} control_port={udp_control_port}",
        )

    data = _load_yaml_mapping(source_config)
    runtime_root.mkdir(parents=True, exist_ok=True)

    runtime_data = runtime_root / "data"
    rollback_dir = runtime_root / "rollback"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    if data_seed_dir is None:
        runtime_data.mkdir(parents=True, exist_ok=True)
    else:
        if not data_seed_dir.is_dir():
            raise FileNotFoundError(f"Seed data dir does not exist: {data_seed_dir}")
        shutil.copytree(data_seed_dir, runtime_data)

    server = _mapping_section(data, "server")
    server["host"] = host
    server["port"] = port

    udp = _mapping_section(data, "udp")
    udp["data_host"] = host
    udp["data_port"] = udp_data_port
    udp["control_host"] = host
    udp["control_port"] = udp_control_port

    gps = _mapping_section(data, "gps")
    gps["gps_enabled"] = False

    ap = _mapping_section(data, "ap")
    self_heal = _mapping_section(ap, "self_heal")
    self_heal["enabled"] = False
    self_heal["state_file"] = str(runtime_data / "hotspot-self-heal-state.json")

    logging = _mapping_section(data, "logging")
    logging["history_db_path"] = str(runtime_data / "history.db")
    logging["app_log_path"] = str(runtime_data / "app.log")

    update = _mapping_section(data, "update")
    update["rollback_dir"] = str(rollback_dir)

    config_path = runtime_root / config_name
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return IsolatedRuntimePaths(
        root=runtime_root,
        data_dir=runtime_data,
        rollback_dir=rollback_dir,
        config_path=config_path,
    )


def build_isolated_server_env(
    runtime_root: Path,
    *,
    repo_root: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    data_dir = runtime_root / "data"
    rollback_dir = runtime_root / "rollback"
    firmware_dir = runtime_root / "firmware"
    data_dir.mkdir(parents=True, exist_ok=True)
    rollback_dir.mkdir(parents=True, exist_ok=True)
    firmware_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["VIBESENSOR_UPDATE_STATE_PATH"] = str(data_dir / "update_status.json")
    env["VIBESENSOR_FIRMWARE_CACHE_DIR"] = str(firmware_dir)
    env["VIBESENSOR_ROLLBACK_DIR"] = str(rollback_dir)
    if repo_root is not None:
        env["VIBESENSOR_REPO_PATH"] = str(repo_root)
    if extra_env:
        env.update(extra_env)
    return env


def build_server_subprocess_cmd(config_path: Path) -> list[str]:
    return [sys.executable, "-c", _SERVER_SUBPROCESS_BOOTSTRAP, str(config_path)]


def start_server_subprocess(
    config_path: Path,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    stdout: IO[str] | int | None = subprocess.PIPE,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        build_server_subprocess_cmd(config_path),
        stdout=stdout,
        stderr=subprocess.STDOUT,
        text=True,
        env=None if env is None else dict(env),
        cwd=None if cwd is None else str(cwd),
        start_new_session=True,
    )


def _signal_process_group(
    process: subprocess.Popen[str],
    *,
    signum: int,
) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            if signum == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
            return
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return


def terminate_subprocess(
    process: subprocess.Popen[str],
    *,
    timeout_s: float = 10.0,
    kill_timeout_s: float = 5.0,
) -> None:
    if process.poll() is not None:
        return
    _signal_process_group(process, signum=signal.SIGTERM)
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _signal_process_group(process, signum=signal.SIGKILL)
        process.wait(timeout=kill_timeout_s)
