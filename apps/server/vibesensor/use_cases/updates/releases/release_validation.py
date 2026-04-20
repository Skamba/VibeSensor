"""Release and artifact validation helpers used by CI and release workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from vibesensor.use_cases.updates.artifact_validation import wheel_metadata_validation_errors

_RELEASE_SMOKE_RETRY_WAIT_S = 0.5


def _sha256_file(path: Path) -> str:
    """Hash a file as lowercase SHA-256 for release validation checks."""

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
    from vibesensor.shared.subprocess_server import build_isolated_server_config

    udp_data_port = port + 1000
    udp_control_port = port + 1001
    return build_isolated_server_config(
        source_config,
        runtime_root,
        host=host,
        port=port,
        udp_data_port=udp_data_port,
        udp_control_port=udp_control_port,
        config_name="release-smoke.yaml",
    ).config_path


def validate_firmware_dist(dist_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = dist_dir / "flash.json"
    if not manifest_path.is_file():
        return [f"Missing firmware manifest: {manifest_path}"]

    try:
        manifest = json.loads(manifest_path.read_bytes())
    except json.JSONDecodeError as exc:
        return [f"Invalid firmware manifest JSON: {exc}"]
    except OSError as exc:
        return [str(exc)]

    if not isinstance(manifest, dict):
        return ["Firmware manifest root must be a JSON object"]

    environments = manifest.get("environments", [])
    if not isinstance(environments, list):
        return ["Firmware manifest environments must be a JSON array"]
    if not environments:
        return ["Firmware manifest must contain at least one environment"]

    seen_names: set[str] = set()
    for index, environment in enumerate(environments):
        prefix = f"environments[{index}]"
        if not isinstance(environment, dict):
            errors.append(f"{prefix} must be a JSON object")
            continue

        env_name = environment.get("name", "")
        if not isinstance(env_name, str) or not env_name:
            errors.append(f"{prefix}.name must be a non-empty string")
            continue
        if env_name in seen_names:
            errors.append(f"Duplicate firmware environment name: {env_name}")
        seen_names.add(env_name)

        segments = environment.get("segments", [])
        if not isinstance(segments, list) or not segments:
            errors.append(f"{prefix}.segments must contain at least one segment")
            continue

        firmware_seen = False
        for seg_index, segment in enumerate(segments):
            seg_prefix = f"{prefix}.segments[{seg_index}]"
            if not isinstance(segment, dict):
                errors.append(f"{seg_prefix} must be a JSON object")
                continue

            file_name = segment.get("file", "")
            offset = segment.get("offset", "")
            sha256 = segment.get("sha256", "")
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


def validate_release_wheel_metadata(
    wheel_path: Path,
    *,
    expected_version: str,
) -> list[str]:
    """Return metadata validation errors for a built server release wheel."""

    return wheel_metadata_validation_errors(
        wheel_path,
        expected_name="vibesensor",
        expected_version=expected_version,
    )


def _read_http(url: str) -> tuple[int, str, str]:
    """Fetch a URL and return status, content type, and decoded body text."""

    request = Request(url, headers={"Connection": "close"})
    try:
        with urlopen(request, timeout=3.0) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
            return response.status, response.headers.get("Content-Type", ""), body
    except HTTPError as exc:
        charset = exc.headers.get_content_charset() if exc.headers is not None else None
        body = exc.read().decode(charset or "utf-8", errors="replace")
        content_type = exc.headers.get("Content-Type", "") if exc.headers is not None else ""
        return exc.code, content_type, body
    except URLError as exc:
        reason = exc.reason if exc.reason is not None else exc
        raise OSError(f"release smoke network request failed for {url}: {reason}") from exc


def packaged_static_index_path() -> Path:
    """Resolve the packaged UI index.html path from the installed app module."""

    import importlib

    app_module = importlib.import_module("vibesensor.app")
    module_file = app_module.__file__
    if module_file is None:
        raise RuntimeError("vibesensor.app module is missing __file__")
    return Path(module_file).resolve().parent.parent / "static" / "index.html"


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
    from vibesensor.shared.subprocess_server import (
        build_isolated_server_env,
        start_server_subprocess,
        terminate_subprocess,
    )

    if require_packaged_static:
        validate_packaged_static_assets()

    with tempfile.TemporaryDirectory(prefix="vibesensor-release-smoke-") as tmp_dir_text:
        tmp_dir = Path(tmp_dir_text)
        config_path = build_release_smoke_config(source_config, tmp_dir, host=host, port=port)
        env = build_isolated_server_env(
            tmp_dir,
            extra_env=extra_env,
        )
        process = start_server_subprocess(
            config_path,
            env=env,
            stdout=subprocess.PIPE,
        )
        try:
            health_url = f"http://{host}:{port}/api/health"
            index_url = f"http://{host}:{port}/index.html"
            last_error: Exception | None = None
            deadline = time.monotonic() + startup_timeout_s
            while True:
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
                        raise RuntimeError(
                            f"Static index content type mismatch: {index_type}",
                        )
                    if "VibeSensor" not in index_body:
                        raise RuntimeError(
                            "Static index content did not include application title",
                        )
                    return
                except (
                    OSError,
                    RuntimeError,
                    json.JSONDecodeError,
                ) as exc:
                    last_error = exc
                    now = time.monotonic()
                    if now >= deadline:
                        output = process.stdout.read() if process.stdout is not None else ""
                        raise RuntimeError(
                            "Release smoke validation timed out waiting for server readiness.\n"
                            f"Last error: {last_error}\n"
                            f"Output:\n{output}",
                        ) from exc
                    remaining = deadline - now
                    time.sleep(min(_RELEASE_SMOKE_RETRY_WAIT_S, remaining))
        finally:
            terminate_subprocess(process)


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


def _cmd_validate_wheel_metadata(args: argparse.Namespace) -> int:
    errors = validate_release_wheel_metadata(
        args.wheel_path,
        expected_version=args.expected_version,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Validated release wheel metadata: {args.wheel_path}")
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

    wheel_parser = subparsers.add_parser(
        "validate-wheel-metadata",
        help="Validate built server wheel metadata for release publishing",
    )
    wheel_parser.add_argument("--wheel-path", type=Path, required=True)
    wheel_parser.add_argument("--expected-version", required=True)
    wheel_parser.set_defaults(handler=_cmd_validate_wheel_metadata)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
