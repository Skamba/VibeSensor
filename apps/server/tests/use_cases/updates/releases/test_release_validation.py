from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from _paths import SERVER_ROOT

from vibesensor.use_cases.updates.releases import release_validation
from vibesensor.use_cases.updates.releases.release_validation import (
    build_release_smoke_config,
    run_server_smoke,
    validate_firmware_dist,
    validate_packaged_static_assets,
    validate_release_wheel_metadata,
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
        "data_host": "127.0.0.1",
        "data_port": 19080,
        "control_host": "127.0.0.1",
        "control_port": 19081,
    }
    assert data["gps"]["gps_enabled"] is False
    assert data["ap"]["self_heal"]["enabled"] is False
    assert data["logging"]["history_db_path"].endswith("history.db")
    assert data["logging"]["app_log_path"].endswith("app.log")
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


def test_validate_firmware_dist_reports_invalid_manifest_json(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "flash.json").write_text("{not-json", encoding="utf-8")

    errors = validate_firmware_dist(dist_dir)

    assert any("Invalid firmware manifest JSON" in error for error in errors)


def test_validate_firmware_dist_reports_missing_environment_name(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    env_dir = dist_dir / "esp32dev"
    env_dir.mkdir(parents=True)
    (env_dir / "firmware.bin").write_bytes(b"firmware")
    manifest = {
        "generated_from": "deadbeef",
        "environments": [
            {
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

    errors = validate_firmware_dist(dist_dir)

    assert "environments[0].name must be a non-empty string" in errors


def test_validate_firmware_dist_reports_checksum_mismatch(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    env_dir = dist_dir / "esp32dev"
    env_dir.mkdir(parents=True)
    (env_dir / "firmware.bin").write_bytes(b"firmware")
    manifest = {
        "generated_from": "deadbeef",
        "environments": [
            {
                "name": "esp32dev",
                "segments": [
                    {
                        "file": "esp32dev/firmware.bin",
                        "offset": "0x10000",
                        "sha256": "0" * 64,
                    },
                ],
            },
        ],
    }
    (dist_dir / "flash.json").write_text(json.dumps(manifest), encoding="utf-8")

    errors = validate_firmware_dist(dist_dir)

    assert any("sha256 mismatch for esp32dev/firmware.bin" in error for error in errors)


def _build_fake_release_wheel(
    path: Path,
    *,
    version: str,
    name: str = "vibesensor",
    requires_python: str = "",
    requires_dist: tuple[str, ...] = (),
) -> None:
    import zipfile

    dist_info = f"vibesensor-{version}.dist-info"
    metadata_lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
    ]
    if requires_python:
        metadata_lines.append(f"Requires-Python: {requires_python}")
    metadata_lines.extend(f"Requires-Dist: {entry}" for entry in requires_dist)
    with zipfile.ZipFile(path, "w") as wheel_zip:
        wheel_zip.writestr("vibesensor/__init__.py", f"__version__ = '{version}'\n")
        wheel_zip.writestr(f"{dist_info}/METADATA", "\n".join(metadata_lines) + "\n")
        wheel_zip.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")


def test_validate_release_wheel_metadata_accepts_matching_wheel(tmp_path: Path) -> None:
    wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_release_wheel(
        wheel_path,
        version="2025.6.15",
        requires_python=">=3.13",
        requires_dist=("packaging>=24,<27",),
    )

    assert (
        validate_release_wheel_metadata(
            wheel_path,
            expected_version="2025.6.15",
        )
        == []
    )


def test_validate_release_wheel_metadata_rejects_version_mismatch(tmp_path: Path) -> None:
    wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_release_wheel(wheel_path, version="2025.6.14")

    errors = validate_release_wheel_metadata(
        wheel_path,
        expected_version="2025.6.15",
    )

    assert any("does not match expected '2025.6.15'" in error for error in errors)


def test_release_validation_cli_validate_wheel_metadata_does_not_require_optional_deps(
    tmp_path: Path,
) -> None:
    wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    _build_fake_release_wheel(wheel_path, version="2025.6.15")
    script = textwrap.dedent(
        f"""
        import importlib.abc
        import runpy
        import sys

        class _BlockOptionalDeps(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                blocked = {{"httpx", "msgspec", "pydantic", "tenacity"}}
                if fullname in blocked or any(fullname.startswith(name + ".") for name in blocked):
                    raise ModuleNotFoundError(f"No module named '{{fullname}}'")
                return None

        sys.meta_path.insert(0, _BlockOptionalDeps())
        sys.argv = [
            "vibesensor.use_cases.updates.releases.release_validation",
            "validate-wheel-metadata",
            "--wheel-path",
            {str(wheel_path)!r},
            "--expected-version",
            "2025.6.15",
        ]
        runpy.run_module(
            "vibesensor.use_cases.updates.releases.release_validation",
            run_name="__main__",
        )
        """,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVER_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Validated release wheel metadata" in result.stdout


def test_release_validation_cli_validate_firmware_manifest_does_not_require_optional_deps(
    tmp_path: Path,
) -> None:
    dist_dir = tmp_path / "dist"
    env_dir = dist_dir / "esp32dev"
    env_dir.mkdir(parents=True)
    firmware_bin = env_dir / "firmware.bin"
    firmware_bin.write_bytes(b"firmware")
    (dist_dir / "flash.json").write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    script = textwrap.dedent(
        f"""
        import importlib.abc
        import runpy
        import sys

        class _BlockOptionalDeps(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                blocked = {{"httpx", "msgspec", "pydantic", "tenacity"}}
                if fullname in blocked or any(fullname.startswith(name + ".") for name in blocked):
                    raise ModuleNotFoundError(f"No module named '{{fullname}}'")
                return None

        sys.meta_path.insert(0, _BlockOptionalDeps())
        sys.argv = [
            "vibesensor.use_cases.updates.releases.release_validation",
            "validate-firmware-manifest",
            "--dist-dir",
            {str(dist_dir)!r},
        ]
        runpy.run_module(
            "vibesensor.use_cases.updates.releases.release_validation",
            run_name="__main__",
        )
        """,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SERVER_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Validated firmware manifest" in result.stdout


def _patch_release_smoke_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    recorded: dict[str, object],
) -> None:
    monkeypatch.setattr(release_validation, "_RELEASE_SMOKE_RETRY_WAIT_S", 0.0)

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

    def fake_start_server_subprocess(
        config_path: Path,
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        stdout=None,
    ):
        recorded["popen"] = (
            (config_path,),
            {
                "env": env,
                "cwd": cwd,
                "stdout": stdout,
            },
        )
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
    import vibesensor.shared.subprocess_server as _subprocess_server

    monkeypatch.setattr(
        _subprocess_server,
        "start_server_subprocess",
        fake_start_server_subprocess,
    )
    monkeypatch.setattr(
        _subprocess_server,
        "terminate_subprocess",
        lambda process: (process.terminate(), process.wait(timeout=10.0)),
    )


def test_run_server_smoke_probes_health_and_static(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}
    _patch_release_smoke_process(monkeypatch, tmp_path, recorded)
    responses = [
        (
            200,
            "application/json",
            '{"status":"ok","startup_state":"ready","background_task_failures":{}}',
        ),
        (200, "text/html; charset=utf-8", "<html><title>VibeSensor</title></html>"),
    ]
    monkeypatch.setattr(release_validation, "_read_http", lambda url: responses.pop(0))

    run_server_smoke(
        SERVER_ROOT / "config.dev.yaml",
        host="127.0.0.1",
        port=18081,
        startup_timeout_s=5.0,
        extra_env={"VIBESENSOR_SERVE_STATIC": "0"},
    )

    popen_args, popen_kwargs = recorded["popen"]
    assert str(popen_args[0]).endswith("release-smoke.yaml")
    assert "VIBESENSOR_DISABLE_AUTO_APP" not in popen_kwargs["env"]
    assert popen_kwargs["env"]["VIBESENSOR_SERVE_STATIC"] == "0"
    assert popen_kwargs["env"]["VIBESENSOR_UPDATE_STATE_PATH"].endswith("update_status.json")
    assert popen_kwargs["stdout"] == subprocess.PIPE
    assert recorded["terminated"] is True


def test_run_server_smoke_retries_until_server_is_ready(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}
    _patch_release_smoke_process(monkeypatch, tmp_path, recorded)
    responses = [
        (
            200,
            "application/json",
            '{"status":"ok","startup_state":"booting","background_task_failures":{}}',
        ),
        (
            200,
            "application/json",
            '{"status":"ok","startup_state":"ready","background_task_failures":{}}',
        ),
        (200, "text/html; charset=utf-8", "<html><title>VibeSensor</title></html>"),
    ]
    monkeypatch.setattr(release_validation, "_read_http", lambda url: responses.pop(0))

    run_server_smoke(
        SERVER_ROOT / "config.dev.yaml",
        host="127.0.0.1",
        port=18081,
        startup_timeout_s=1.0,
    )

    assert responses == []
    assert recorded["terminated"] is True


def test_run_server_smoke_times_out_with_last_error(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}
    _patch_release_smoke_process(monkeypatch, tmp_path, recorded)
    monkeypatch.setattr(
        release_validation,
        "_read_http",
        lambda url: (503, "text/plain", "still starting"),
    )

    with pytest.raises(
        RuntimeError,
        match="Release smoke validation timed out waiting for server readiness",
    ):
        run_server_smoke(
            SERVER_ROOT / "config.dev.yaml",
            host="127.0.0.1",
            port=18081,
            startup_timeout_s=0.0,
        )

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

    with pytest.raises(RuntimeError, match="Missing packaged UI asset"):
        validate_packaged_static_assets()
