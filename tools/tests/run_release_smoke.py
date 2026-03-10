#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    run_env = None if env is None else {**os.environ, **env}
    subprocess.run(cmd, cwd=str(cwd), check=True, env=run_env)


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / "bin" / "python"


def _resolve_repo_path(repo_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (repo_root / path)


def _build_server_wheel(repo_root: Path) -> Path:
    dist_dir = repo_root / "apps" / "server" / "dist"
    shutil.rmtree(dist_dir, ignore_errors=True)
    with tempfile.TemporaryDirectory(
        prefix="vibesensor-release-build-venv-"
    ) as venv_text:
        build_venv = Path(venv_text)
        venv.EnvBuilder(with_pip=True).create(build_venv)
        build_python = _venv_python(build_venv)
        _run(
            [str(build_python), "-m", "pip", "install", "--upgrade", "pip", "build"],
            cwd=repo_root,
        )
        _run(
            [str(build_python), "-m", "build", "--wheel", "apps/server/"], cwd=repo_root
        )
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"No wheel produced in {dist_dir}")
    return wheels[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build packaged UI + server wheel and run the release smoke validator."
    )
    parser.add_argument(
        "--config",
        default="apps/server/config.dev.yaml",
        help="Config file used by the smoke validator.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Smoke server bind host.")
    parser.add_argument(
        "--port", default="18080", type=int, help="Smoke server bind port."
    )
    parser.add_argument(
        "--skip-npm-ci",
        action="store_true",
        help="Skip npm ci inside tools/build_ui_static.py.",
    )
    parser.add_argument(
        "--skip-ui-build",
        action="store_true",
        help="Reuse already-built static assets instead of rebuilding the UI.",
    )
    parser.add_argument(
        "--wheel-path",
        default=None,
        help="Use an existing wheel instead of building apps/server/dist/*.whl.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    python_cmd = sys.executable

    if not args.skip_ui_build:
        build_ui_cmd = [python_cmd, "tools/build_ui_static.py"]
        if args.skip_npm_ci:
            build_ui_cmd.append("--skip-npm-ci")
        _run(build_ui_cmd, cwd=repo_root)

    if args.wheel_path:
        wheel_path = _resolve_repo_path(repo_root, args.wheel_path).resolve()
        if wheel_path.suffix != ".whl" or not wheel_path.is_file():
            raise RuntimeError(
                f"Wheel path does not exist or is not a .whl file: {wheel_path}"
            )
    else:
        wheel_path = _build_server_wheel(repo_root)

    with tempfile.TemporaryDirectory(
        prefix="vibesensor-release-smoke-venv-"
    ) as venv_text:
        venv_dir = Path(venv_text)
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        smoke_python = _venv_python(venv_dir)
        _run(
            [str(smoke_python), "-m", "pip", "install", "--upgrade", "pip"],
            cwd=repo_root,
        )
        _run(
            [str(smoke_python), "-m", "pip", "install", str(wheel_path)], cwd=repo_root
        )
        _run(
            [
                str(smoke_python),
                "-m",
                "vibesensor.release_validation",
                "smoke-server",
                "--config",
                args.config,
                "--host",
                args.host,
                "--port",
                str(args.port),
            ],
            cwd=repo_root,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
