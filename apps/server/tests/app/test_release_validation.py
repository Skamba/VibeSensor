from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from _paths import SERVER_ROOT

from vibesensor import release_validation
from vibesensor.release_validation import (
    build_release_smoke_config,
    run_server_smoke,
    validate_firmware_dist,
    validate_packaged_static_assets,
)


def test_build_release_smoke_config_rewrites_runtime_paths(tmp_path: Path) -> None:
    config_path = build_release_smoke_config(
        SERVER_ROOT / "config.dev.yaml",
        tmp_path,
        host="127.0.0.1",
        port=18080,
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert data["server"] == {"port": 18080, "host": "127.0.0.1"}
    assert data["udp"] == {
        "data_listen": "127.0.0.1:19080",
        "control_listen": "127.0.0.1:19081",
    }
    assert data["gps"]["gps_enabled"] is False
    assert data["ap"]["self_heal"]["enabled"] is False
    assert data["logging"]["history_db_path"].endswith("history.db")
    assert data["update"]["rollback_dir"].endswith("rollback")


def test_validate_firmware_dist_accepts_generated_manifest(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    env_dir = dist_dir / "esp32dev"
    env_dir.mkdir(parents=True)
    firmware_bin = env_dir / "firmware.bin"
    firmware_bin.write_bytes(b"firmware")
    manifest = {
        "generated_from": "deadbeef",
        "environments": [
            {
                "name": "esp32dev",
                "segments": [
                    {
                        "file": "esp32dev/firmware.bin",
                        "offset": "0x10000",
                        "sha256": hashlib.sha256(b"firmware").hexdigest(),
                    },
                ],
            },
        ],
    }
    (dist_dir / "flash.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert validate_firmware_dist(dist_dir) == []


def test_validate_firmware_dist_reports_missing_firmware_bin(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True)
    manifest = {
        "generated_from": "deadbeef",
        "environments": [{"name": "esp32dev", "segments": []}],
    }
    (dist_dir / "flash.json").write_text(json.dumps(manifest), encoding="utf-8")

    errors = validate_firmware_dist(dist_dir)
    assert any("must contain at least one segment" in error for error in errors)


def test_run_server_smoke_probes_health_and_static(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = SimpleNamespace(read=lambda: "")

        def poll(self):
            return None

        def terminate(self) -> None:
            recorded["terminated"] = True

        def wait(self, timeout: float | None = None) -> int:
            recorded["wait_timeout"] = timeout
            return 0

        def kill(self) -> None:
            raise AssertionError("kill should not be called for a healthy process")

    def fake_popen(*args, **kwargs):
        recorded["popen"] = (args, kwargs)
        return FakeProcess()

    def fake_build_release_smoke_config(
        source_config: Path,
        runtime_root: Path,
        *,
        host: str,
        port: int,
    ) -> Path:
        config_path = tmp_path / "release-smoke.yaml"
        config_path.write_text("server:\n  host: 127.0.0.1\n  port: 18081\n", encoding="utf-8")
        recorded["config"] = (source_config, runtime_root, host, port)
        return config_path

    responses = [
        (
            200,
            "application/json",
            '{"status":"ok","startup_state":"ready","background_task_failures":{}}',
        ),
        (200, "text/html; charset=utf-8", "<html><title>VibeSensor</title></html>"),
    ]

    monkeypatch.setattr(
        release_validation,
        "build_release_smoke_config",
        fake_build_release_smoke_config,
    )
    monkeypatch.setattr(
        release_validation,
        "validate_packaged_static_assets",
        lambda: tmp_path / "index.html",
    )
    monkeypatch.setattr(release_validation.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(release_validation, "_read_http", lambda url: responses.pop(0))

    run_server_smoke(
        SERVER_ROOT / "config.dev.yaml",
        host="127.0.0.1",
        port=18081,
        startup_timeout_s=5.0,
        extra_env={"VIBESENSOR_SERVE_STATIC": "0"},
    )

    popen_args, popen_kwargs = recorded["popen"]
    assert list(popen_args[0][:2]) == [release_validation.sys.executable, "-c"]
    assert "from vibesensor.app import create_app" in popen_args[0][2]
    assert popen_args[0][3].endswith("release-smoke.yaml")
    assert popen_kwargs["env"]["VIBESENSOR_DISABLE_AUTO_APP"] == "1"
    assert popen_kwargs["env"]["VIBESENSOR_SERVE_STATIC"] == "0"
    assert popen_kwargs["env"]["VIBESENSOR_UPDATE_STATE_PATH"].endswith("update_status.json")
    assert recorded["terminated"] is True


def test_validate_packaged_static_assets_requires_index(monkeypatch) -> None:
    original_is_file = Path.is_file
    static_dir = Path("/tmp/fake-vibesensor") / "static"

    def fake_import_module(name: str):
        class _Module:
            __file__ = str(static_dir / "app.py")

        return _Module()

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: False if self == static_dir / "index.html" else original_is_file(self),
    )

    try:
        validate_packaged_static_assets()
    except RuntimeError as exc:
        assert "Missing packaged UI asset" in str(exc)
    else:
        raise AssertionError("Expected missing packaged UI asset failure")
