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


def _build_server_wheel(repo_root: Path) -> Path:
    dist_dir = repo_root / "apps" / "server" / "dist"
    shutil.rmtree(dist_dir, ignore_errors=True)
    with tempfile.TemporaryDirectory(prefix="vibesensor-release-build-venv-") as venv_text:
        build_venv = Path(venv_text)
        venv.EnvBuilder(with_pip=True).create(build_venv)
        build_python = _venv_python(build_venv)
        _run([str(build_python), "-m", "pip", "install", "--upgrade", "pip", "build"], cwd=repo_root)
        _run([str(build_python), "-m", "build", "--wheel", "apps/server/"], cwd=repo_root)
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"No wheel produced in {dist_dir}")
    return wheels[-1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build packaged UI + server wheel and run the release smoke validator."
    )
    parser.add_argument(
        "--config",
        default="apps/server/config.dev.yaml",
        help="Config file used by the smoke validator.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Smoke server bind host.")
    parser.add_argument("--port", default="18080", type=int, help="Smoke server bind port.")
    parser.add_argument(
        "--skip-npm-ci",
        action="store_true",
        help="Skip npm ci inside tools/build_ui_static.py.",
    )
    parser.add_argument(
        "--contracts-dir",
        default="libs/shared/contracts",
        help="Shared contracts directory to expose as VIBESENSOR_CONTRACTS_DIR during smoke validation.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    python_cmd = sys.executable
    contracts_dir = (repo_root / args.contracts_dir).resolve()

    build_ui_cmd = [python_cmd, "tools/build_ui_static.py"]
    if args.skip_npm_ci:
        build_ui_cmd.append("--skip-npm-ci")
    _run(build_ui_cmd, cwd=repo_root)

    wheel_path = _build_server_wheel(repo_root)

    with tempfile.TemporaryDirectory(prefix="vibesensor-release-smoke-venv-") as venv_text:
        venv_dir = Path(venv_text)
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        smoke_python = _venv_python(venv_dir)
        _run([str(smoke_python), "-m", "pip", "install", "--upgrade", "pip"], cwd=repo_root)
        _run([str(smoke_python), "-m", "pip", "install", str(wheel_path)], cwd=repo_root)
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
            env={"VIBESENSOR_CONTRACTS_DIR": str(contracts_dir)},
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())