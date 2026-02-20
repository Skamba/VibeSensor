from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

LOCAL_SERVER_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


def _normalize_http_host(host: str) -> str:
    return "127.0.0.1" if host == "0.0.0.0" else host


def server_health_url(host: str, port: int) -> str:
    return f"http://{_normalize_http_host(host)}:{port}/api/clients"


def _speed_override_url(host: str, port: int) -> str:
    return f"http://{_normalize_http_host(host)}:{port}/api/simulator/speed-override"


def check_server_running(host: str, port: int, timeout_s: float = 1.0) -> bool:
    url = server_health_url(host, port)
    try:
        with urlopen(url, timeout=timeout_s) as resp:
            return resp.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def set_server_speed_override_kmh(
    host: str, port: int, speed_kmh: float, timeout_s: float
) -> float | None:
    payload = json.dumps({"speed_kmh": float(speed_kmh)}).encode("utf-8")
    req = Request(
        _speed_override_url(host, port),
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout_s) as resp:
        body = resp.read()
    parsed = json.loads(body.decode("utf-8")) if body else {}
    value = parsed.get("speed_kmh")
    return float(value) if isinstance(value, (int, float)) else None


def _start_local_server(config_path: Path, repo_root: Path) -> subprocess.Popen[str]:
    cmd = [sys.executable, "-m", "vibesensor.app", "--config", str(config_path)]
    return subprocess.Popen(cmd, cwd=str(repo_root / "apps" / "server"))


def maybe_start_server(
    args: argparse.Namespace, repo_root: Path
) -> subprocess.Popen[str] | None:
    host = args.server_host.strip().lower()
    if host not in LOCAL_SERVER_HOSTS:
        print(
            f"Auto-start skipped: server host {args.server_host!r} is not local. "
            "Start the server manually on that host."
        )
        return None

    for _ in range(5):
        if check_server_running(
            args.server_host, args.server_http_port, timeout_s=args.server_check_timeout
        ):
            print(
                f"Server already running at {server_health_url(args.server_host, args.server_http_port)}"
            )
            return None
        time.sleep(0.2)

    if check_server_running(
        args.server_host, args.server_http_port, timeout_s=args.server_check_timeout
    ):
        print(
            f"Server already running at {server_health_url(args.server_host, args.server_http_port)}"
        )
        return None

    config_path = Path(args.server_config)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    print(f"Server not reachable. Starting local app with config: {config_path}")
    proc = _start_local_server(config_path, repo_root)
    deadline = time.monotonic() + args.server_start_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            if check_server_running(
                args.server_host,
                args.server_http_port,
                timeout_s=args.server_check_timeout,
            ):
                print(
                    "Detected existing healthy server after auto-start race at "
                    f"{server_health_url(args.server_host, args.server_http_port)}"
                )
                return None
            raise RuntimeError(
                f"Auto-started server exited early with code {proc.returncode}"
            )
        if check_server_running(
            args.server_host, args.server_http_port, timeout_s=args.server_check_timeout
        ):
            print(
                f"Server is now reachable at {server_health_url(args.server_host, args.server_http_port)}"
            )
            return proc
        time.sleep(0.3)
    proc.terminate()
    raise RuntimeError("Auto-started server did not become ready before timeout")
