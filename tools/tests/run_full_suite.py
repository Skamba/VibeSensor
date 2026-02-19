from __future__ import annotations

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
CONTAINER = f"vibesensor-full-suite-{os.getpid()}"
BASE_URL = "http://127.0.0.1:18000"


def _run(
    cmd: list[str], *, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT), check=check, text=True, env=env)


def _api_snapshot(path: str) -> str:
    try:
        with urlopen(f"{BASE_URL}{path}", timeout=5) as resp:
            payload = json.loads(resp.read())
        return json.dumps(payload, indent=2, sort_keys=True)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return f"<unavailable: {exc}>"


def _print_diagnostics(sim_log: Path) -> None:
    print("\n=== diagnostics: docker ps ===", flush=True)
    _run(["docker", "ps", "-a"], check=False)
    print("\n=== diagnostics: docker inspect state ===", flush=True)
    _run(["docker", "inspect", CONTAINER, "--format", "{{json .State}}"], check=False)
    print("\n=== diagnostics: docker logs (tail 200) ===", flush=True)
    _run(["docker", "logs", "--tail", "200", CONTAINER], check=False)
    print("\n=== diagnostics: /api/clients ===", flush=True)
    print(_api_snapshot("/api/clients"), flush=True)
    print("\n=== diagnostics: /api/history ===", flush=True)
    print(_api_snapshot("/api/history"), flush=True)
    print("\n=== diagnostics: simulator log ===", flush=True)
    if sim_log.exists():
        print(sim_log.read_text(encoding="utf-8"), flush=True)
    else:
        print("<no simulator log>", flush=True)


def _wait_health(timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{BASE_URL}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(1.0)
    raise RuntimeError("Container did not become healthy in time")


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="vibesensor-e2e-data-"))
    shutil.copytree(ROOT / "apps" / "server" / "data", data_dir, dirs_exist_ok=True)
    sim_log = data_dir / "sim_sender.log"
    container_started = False
    try:
        _run(["python3", "tools/sync_ui_to_pi_public.py"])
        _run(
            ["python3", "-m", "pytest", "-q", "-m", "not selenium", "apps/server/tests"]
        )

        _run(
            [
                "docker",
                "build",
                "-f",
                "infra/docker/server.Dockerfile",
                "-t",
                IMAGE,
                ".",
            ]
        )
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                CONTAINER,
                "-p",
                "18000:8000",
                "-p",
                "19000:9000/udp",
                "-p",
                "19001:9001/udp",
                "-v",
                f"{data_dir}:/app/apps/server/data",
                IMAGE,
            ]
        )
        container_started = True
        _wait_health()

        env = os.environ.copy()
        env.update(
            {
                "VIBESENSOR_BASE_URL": BASE_URL,
                "VIBESENSOR_SIM_SERVER_HOST": "127.0.0.1",
                "VIBESENSOR_SIM_DATA_PORT": "19000",
                "VIBESENSOR_SIM_CONTROL_PORT": "19001",
                "VIBESENSOR_SIM_DURATION": "12",
                "VIBESENSOR_SIM_LOG": str(sim_log),
            }
        )
        _run(
            [
                "python3",
                "-m",
                "pytest",
                "-q",
                "apps/server/tests_e2e/test_e2e_docker_rear_left_wheel_fault.py",
            ],
            env=env,
        )
        return 0
    except subprocess.CalledProcessError:
        _print_diagnostics(sim_log)
        return 1
    except Exception:
        _print_diagnostics(sim_log)
        raise
    finally:
        if container_started:
            _run(["docker", "rm", "-f", CONTAINER], check=False)
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
