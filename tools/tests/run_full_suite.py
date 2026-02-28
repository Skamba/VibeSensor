from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "vibesensor-full-suite"
CONTAINER_PREFIX = "vibesensor-full-suite"


def _run(
    cmd: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(cwd), check=check, text=True, env=env)


def _api_snapshot(base_url: str, path: str) -> str:
    try:
        with urlopen(f"{base_url}{path}", timeout=5) as resp:
            payload = json.loads(resp.read())
        return json.dumps(payload, indent=2, sort_keys=True)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"<unavailable: {exc}>"


def _print_diagnostics(*, sim_log: Path, container_name: str, base_url: str) -> None:
    print("\n=== diagnostics: docker ps ===", flush=True)
    _run(["docker", "ps", "-a"], check=False)
    print("\n=== diagnostics: docker inspect state ===", flush=True)
    _run(
        ["docker", "inspect", container_name, "--format", "{{json .State}}"],
        check=False,
    )
    print("\n=== diagnostics: docker logs (tail 200) ===", flush=True)
    _run(["docker", "logs", "--tail", "200", container_name], check=False)
    print("\n=== diagnostics: /api/clients ===", flush=True)
    print(_api_snapshot(base_url, "/api/clients"), flush=True)
    print("\n=== diagnostics: /api/history ===", flush=True)
    print(_api_snapshot(base_url, "/api/history"), flush=True)
    print("\n=== diagnostics: simulator log ===", flush=True)
    if sim_log.exists():
        print(sim_log.read_text(encoding="utf-8"), flush=True)
    else:
        print("<no simulator log>", flush=True)


def _wait_health(base_url: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(1.0)
    raise RuntimeError("Container did not become healthy in time")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the full VibeSensor CI-aligned suite."
    )
    parser.add_argument(
        "--skip-ui-sync",
        action="store_true",
        help="Skip UI sync/build into apps/server/public.",
    )
    parser.add_argument(
        "--skip-ui-smoke",
        action="store_true",
        help="Skip Playwright install and UI smoke tests.",
    )
    parser.add_argument(
        "--skip-unit-tests",
        action="store_true",
        help="Skip backend unit/integration pytest suite in apps/server/tests.",
    )
    parser.add_argument(
        "--fast-e2e",
        action="store_true",
        help="Run only fast docker e2e tests (exclude long_sim-marked scenarios).",
    )
    parser.add_argument(
        "--pytest-marker",
        default=None,
        help=(
            "Override pytest marker expression for apps/server/tests_e2e "
            "(for example: 'e2e and not long_sim')."
        ),
    )
    parser.add_argument(
        "--pytest-target",
        action="append",
        default=[],
        help=(
            "Optional explicit pytest target(s) for e2e execution. Repeat to pass "
            "multiple node ids or paths."
        ),
    )
    parser.add_argument(
        "--docker-image",
        default=IMAGE,
        help="Docker image name to build/run for the e2e suite.",
    )
    parser.add_argument(
        "--container-name",
        default=f"{CONTAINER_PREFIX}-{os.getpid()}",
        help="Docker container name to use for e2e runtime.",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=18000,
        help="Host HTTP port mapped to container port 8000.",
    )
    parser.add_argument(
        "--sim-data-port",
        type=int,
        default=19000,
        help="Host UDP data port mapped to container port 9000.",
    )
    parser.add_argument(
        "--sim-control-port",
        type=int,
        default=19001,
        help="Host UDP control port mapped to container port 9001.",
    )
    parser.add_argument(
        "--sim-client-control-base",
        type=int,
        default=9100,
        help="Base UDP control port used by local simulator client sockets.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Optional host data dir to mount into /app/apps/server/data.",
    )
    parser.add_argument(
        "--skip-docker-build",
        action="store_true",
        help="Skip docker build and reuse an existing --docker-image.",
    )
    args = parser.parse_args()

    e2e_marker_expr = args.pytest_marker
    if e2e_marker_expr is None:
        e2e_marker_expr = "e2e and not long_sim" if args.fast_e2e else "e2e"
    pytest_targets = args.pytest_target or ["apps/server/tests_e2e"]
    base_url = f"http://127.0.0.1:{args.http_port}"

    cleanup_data_dir = args.data_dir is None
    data_dir = (
        Path(tempfile.mkdtemp(prefix="vibesensor-e2e-data-"))
        if cleanup_data_dir
        else Path(args.data_dir).resolve()
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "apps" / "server" / "data", data_dir, dirs_exist_ok=True)
    sim_log = data_dir / "sim_sender.log"
    container_started = False
    try:
        if not args.skip_ui_sync:
            _run(["python3", "tools/sync_ui_to_pi_public.py"])
        if not args.skip_ui_smoke:
            playwright_marker = ROOT / "apps" / "ui" / ".playwright-chromium-installed"
            if (
                os.environ.get("FORCE_PLAYWRIGHT_INSTALL", "0") == "1"
                or not playwright_marker.exists()
            ):
                _run(
                    ["npx", "playwright", "install", "chromium"],
                    env={**os.environ, "PLAYWRIGHT_SKIP_BROWSER_GC": "1"},
                    cwd=ROOT / "apps" / "ui",
                )
                playwright_marker.write_text("chromium\n", encoding="utf-8")
            _run(["npm", "run", "test:smoke"], cwd=ROOT / "apps" / "ui")
        if not args.skip_unit_tests:
            _run(
                [
                    "python3",
                    "-m",
                    "pytest",
                    "-q",
                    "-m",
                    "not selenium",
                    "apps/server/tests",
                ]
            )

        if not args.skip_docker_build:
            _run(
                [
                    "docker",
                    "build",
                    "-f",
                    "apps/server/Dockerfile",
                    "-t",
                    args.docker_image,
                    ".",
                ]
            )
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                args.container_name,
                "-p",
                f"{args.http_port}:8000",
                "-p",
                f"{args.sim_data_port}:9000/udp",
                "-p",
                f"{args.sim_control_port}:9001/udp",
                "-v",
                f"{data_dir}:/app/apps/server/data",
                args.docker_image,
            ]
        )
        container_started = True
        _wait_health(base_url)

        env = os.environ.copy()
        env.update(
            {
                "VIBESENSOR_BASE_URL": base_url,
                "VIBESENSOR_SIM_SERVER_HOST": "127.0.0.1",
                "VIBESENSOR_SIM_DATA_PORT": str(args.sim_data_port),
                "VIBESENSOR_SIM_CONTROL_PORT": str(args.sim_control_port),
                "VIBESENSOR_SIM_CLIENT_CONTROL_BASE": str(args.sim_client_control_base),
                "VIBESENSOR_SIM_DURATION": "12",
                "VIBESENSOR_SIM_DURATION_LONG": "20",
                "VIBESENSOR_SIM_LOG": str(sim_log),
            }
        )
        _run(
            [
                "python3",
                "-m",
                "pytest",
                "-q",
                "-m",
                e2e_marker_expr,
                *pytest_targets,
            ],
            env=env,
        )
        return 0
    except subprocess.CalledProcessError:
        _print_diagnostics(
            sim_log=sim_log, container_name=args.container_name, base_url=base_url
        )
        return 1
    except Exception:
        _print_diagnostics(
            sim_log=sim_log, container_name=args.container_name, base_url=base_url
        )
        raise
    finally:
        if container_started:
            _run(["docker", "rm", "-f", args.container_name], check=False)
        if cleanup_data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
