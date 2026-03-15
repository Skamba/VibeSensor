"""Release and artifact validation helpers used by CI and release workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release_smoke_config(
    source_config: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
) -> Path:
    import yaml

    data = yaml.safe_load(source_config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected config mapping in {source_config}")

    runtime_data = runtime_root / "data"
    rollback_dir = runtime_root / "rollback"
    runtime_data.mkdir(parents=True, exist_ok=True)
    rollback_dir.mkdir(parents=True, exist_ok=True)

    data.setdefault("server", {})
    data["server"]["host"] = host
    data["server"]["port"] = port

    udp_data_port = port + 1000
    udp_control_port = port + 1001
    if udp_control_port > 65535:
        raise ValueError(
            f"Release smoke UDP ports exceed range for HTTP port {port}: "
            f"{udp_data_port}, {udp_control_port}",
        )
    data.setdefault("udp", {})
    data["udp"]["data_listen"] = f"{host}:{udp_data_port}"
    data["udp"]["control_listen"] = f"{host}:{udp_control_port}"

    data.setdefault("gps", {})
    data["gps"]["gps_enabled"] = False

    data.setdefault("ap", {})
    data["ap"].setdefault("self_heal", {})
    data["ap"]["self_heal"]["enabled"] = False
    data["ap"]["self_heal"]["state_file"] = str(runtime_data / "hotspot-self-heal-state.json")

    data.setdefault("logging", {})
    data["logging"]["history_db_path"] = str(runtime_data / "history.db")

    data.setdefault("update", {})
    data["update"]["rollback_dir"] = str(rollback_dir)

    config_path = runtime_root / "release-smoke.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return config_path


def validate_firmware_dist(dist_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = dist_dir / "flash.json"
    if not manifest_path.is_file():
        return [f"Missing firmware manifest: {manifest_path}"]

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid firmware manifest JSON: {exc}"]

    if not isinstance(manifest_data, dict):
        return ["Firmware manifest root must be a JSON object"]

    environments = manifest_data.get("environments")
    if not isinstance(environments, list) or not environments:
        return ["Firmware manifest must contain at least one environment"]

    seen_names: set[str] = set()
    for index, raw_environment in enumerate(environments):
        prefix = f"environments[{index}]"
        if not isinstance(raw_environment, dict):
            errors.append(f"{prefix} must be an object")
            continue

        env_name = raw_environment.get("name")
        if not isinstance(env_name, str) or not env_name:
            errors.append(f"{prefix}.name must be a non-empty string")
            continue
        if env_name in seen_names:
            errors.append(f"Duplicate firmware environment name: {env_name}")
        seen_names.add(env_name)

        segments = raw_environment.get("segments")
        if not isinstance(segments, list) or not segments:
            errors.append(f"{prefix}.segments must contain at least one segment")
            continue

        firmware_seen = False
        for seg_index, raw_segment in enumerate(segments):
            seg_prefix = f"{prefix}.segments[{seg_index}]"
            if not isinstance(raw_segment, dict):
                errors.append(f"{seg_prefix} must be an object")
                continue

            file_name = raw_segment.get("file")
            offset = raw_segment.get("offset")
            sha256 = raw_segment.get("sha256")
            if not isinstance(file_name, str) or not file_name:
                errors.append(f"{seg_prefix}.file must be a non-empty string")
                continue
            if not isinstance(offset, str) or not offset.startswith("0x"):
                errors.append(f"{seg_prefix}.offset must be a hex string")
            if not isinstance(sha256, str) or len(sha256) != 64:
                errors.append(f"{seg_prefix}.sha256 must be a 64-character hex digest")

            artifact_path = dist_dir / file_name
            if not artifact_path.is_file():
                errors.append(f"{seg_prefix} missing artifact file: {artifact_path}")
                continue

            if artifact_path.name == "firmware.bin":
                firmware_seen = True

            actual_sha = _sha256_file(artifact_path)
            if sha256 != actual_sha:
                errors.append(
                    f"{seg_prefix} sha256 mismatch for {file_name}: "
                    f"expected {sha256}, got {actual_sha}",
                )

        if not firmware_seen:
            errors.append(f"{prefix} does not include firmware.bin")

    return errors


def _read_http(url: str) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"Connection": "close"})
    with urllib.request.urlopen(request, timeout=3.0) as response:
        body = response.read().decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type", "")
        return response.status, content_type, body


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


_SMOKE_SERVER_BOOTSTRAP = "\n".join(
    [
        "import sys",
        "from pathlib import Path",
        "import uvicorn",
        "from vibesensor.app import create_app",
        "config_path = Path(sys.argv[1])",
        "runtime_app = create_app(config_path=config_path)",
        "runtime = runtime_app.state.runtime",
        "uvicorn.run(",
        "    runtime_app,",
        "    host=runtime.config.server.host,",
        "    port=runtime.config.server.port,",
        "    log_level='info',",
        ")",
    ],
)


def packaged_static_index_path() -> Path:
    import importlib

    previous_disable_auto_app = os.environ.get("VIBESENSOR_DISABLE_AUTO_APP")
    os.environ["VIBESENSOR_DISABLE_AUTO_APP"] = "1"
    try:
        app_module = importlib.import_module("vibesensor.app")
    finally:
        if previous_disable_auto_app is None:
            os.environ.pop("VIBESENSOR_DISABLE_AUTO_APP", None)
        else:
            os.environ["VIBESENSOR_DISABLE_AUTO_APP"] = previous_disable_auto_app
    return Path(app_module.__file__).resolve().parent / "static" / "index.html"  # type: ignore[arg-type]


def validate_packaged_static_assets() -> Path:
    index_path = packaged_static_index_path()
    if not index_path.is_file():
        raise RuntimeError(f"Missing packaged UI asset: {index_path}")
    return index_path


def run_server_smoke(
    source_config: Path,
    *,
    host: str,
    port: int,
    startup_timeout_s: float = 45.0,
    require_packaged_static: bool = True,
    extra_env: dict[str, str] | None = None,
) -> None:
    if require_packaged_static:
        validate_packaged_static_assets()

    with tempfile.TemporaryDirectory(prefix="vibesensor-release-smoke-") as tmp_dir_text:
        tmp_dir = Path(tmp_dir_text)
        config_path = build_release_smoke_config(source_config, tmp_dir, host=host, port=port)
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")
        env.setdefault("VIBESENSOR_UPDATE_STATE_PATH", str(tmp_dir / "data" / "update_status.json"))
        if extra_env:
            env.update(extra_env)

        process = subprocess.Popen(
            [sys.executable, "-c", _SMOKE_SERVER_BOOTSTRAP, str(config_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        try:
            deadline = time.monotonic() + startup_timeout_s
            health_url = f"http://{host}:{port}/api/health"
            index_url = f"http://{host}:{port}/index.html"
            last_error: Exception | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout is not None else ""
                    raise RuntimeError(
                        f"Release smoke server exited before becoming healthy.\nOutput:\n{output}",
                    )
                try:
                    status, content_type, body = _read_http(health_url)
                    if status != 200:
                        raise RuntimeError(f"Health endpoint returned HTTP {status}")
                    payload = json.loads(body)
                    if payload.get("status") not in {"ok", "degraded"}:
                        raise RuntimeError(f"Unexpected health payload: {payload}")
                    if payload.get("startup_state") != "ready":
                        raise RuntimeError(f"Server not ready yet: {payload}")
                    if payload.get("background_task_failures"):
                        raise RuntimeError(f"Managed startup task failed: {payload}")
                    index_status, index_type, index_body = _read_http(index_url)
                    if index_status != 200:
                        raise RuntimeError(f"Static index returned HTTP {index_status}")
                    if "text/html" not in index_type:
                        raise RuntimeError(f"Static index content type mismatch: {index_type}")
                    if "VibeSensor" not in index_body:
                        raise RuntimeError("Static index content did not include application title")
                    return
                except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    last_error = exc
                    time.sleep(0.5)

            output = process.stdout.read() if process.stdout is not None else ""
            raise RuntimeError(
                "Release smoke validation timed out waiting for server readiness.\n"
                f"Last error: {last_error}\n"
                f"Output:\n{output}",
            )
        finally:
            _terminate_process(process)


def _cmd_validate_firmware_manifest(args: argparse.Namespace) -> int:
    errors = validate_firmware_dist(args.dist_dir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Validated firmware manifest: {args.dist_dir / 'flash.json'}")
    return 0


def _cmd_smoke_server(args: argparse.Namespace) -> int:
    run_server_smoke(args.config, host=args.host, port=args.port, startup_timeout_s=args.timeout)
    print(f"Validated release server boot path on http://{args.host}:{args.port}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate VibeSensor release artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    smoke_parser = subparsers.add_parser(
        "smoke-server",
        help="Boot the packaged server and probe health/static endpoints",
    )
    smoke_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Base YAML config to adapt for smoke validation",
    )
    smoke_parser.add_argument("--host", default="127.0.0.1")
    smoke_parser.add_argument("--port", type=int, default=18080)
    smoke_parser.add_argument("--timeout", type=float, default=45.0)
    smoke_parser.set_defaults(handler=_cmd_smoke_server)

    firmware_parser = subparsers.add_parser(
        "validate-firmware-manifest",
        help="Validate firmware dist/flash.json and referenced artifacts",
    )
    firmware_parser.add_argument("--dist-dir", type=Path, required=True)
    firmware_parser.set_defaults(handler=_cmd_validate_firmware_manifest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
