from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: bytes
    headers: dict[str, str]


def api_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    expected_status: int | tuple[int, ...] = 200,
    timeout: int = 30,
) -> ApiResponse:
    expected_statuses = (
        (expected_status,) if isinstance(expected_status, int) else tuple(expected_status)
    )
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = Request(f"{base_url}{path}", data=payload, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            if resp.status not in expected_statuses:
                raise AssertionError(
                    f"{method} {path} returned {resp.status}, expected {expected_statuses}"
                )
            return ApiResponse(
                status=resp.status,
                body=resp.read(),
                headers={k.lower(): v for k, v in resp.headers.items()},
            )
    except HTTPError as exc:
        if exc.code not in expected_statuses:
            raise
        return ApiResponse(
            status=exc.code,
            body=exc.read(),
            headers={k.lower(): v for k, v in exc.headers.items()},
        )


def api_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    expected_status: int | tuple[int, ...] = 200,
    timeout: int = 30,
) -> dict:
    resp = api_request(
        base_url,
        path,
        method=method,
        body=body,
        expected_status=expected_status,
        timeout=timeout,
    )
    return json.loads(resp.body) if resp.body else {}


def api_bytes(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    expected_status: int | tuple[int, ...] = 200,
    timeout: int = 30,
) -> ApiResponse:
    return api_request(
        base_url,
        path,
        method=method,
        body=body,
        expected_status=expected_status,
        timeout=timeout,
    )


def pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(filter(None, (page.extract_text() for page in reader.pages))).lower()


def run_simulator(
    *,
    base_url: str,
    sim_host: str,
    sim_data_port: str,
    sim_control_port: str,
    duration_s: float,
    count: int = 4,
    names: str = "front-left,front-right,rear-left,rear-right",
    scenario: str = "one-wheel-mild",
    fault_wheel: str = "rear-left",
    speed_kmh: float = 0.0,
    client_control_base: int | str | None = None,
) -> None:
    control_base = (
        client_control_base
        if client_control_base is not None
        else os.environ.get("VIBESENSOR_SIM_CLIENT_CONTROL_BASE", "9100")
    )
    sim_cmd = [
        sys.executable,
        str(ROOT / "apps" / "simulator" / "sim_sender.py"),
        "--server-host",
        sim_host,
        "--server-data-port",
        sim_data_port,
        "--server-control-port",
        sim_control_port,
        "--server-http-port",
        base_url.rsplit(":", 1)[-1],
        "--count",
        str(count),
        "--names",
        names,
        "--scenario",
        scenario,
        "--fault-wheel",
        fault_wheel,
        "--speed-kmh",
        str(speed_kmh),
        "--duration",
        str(duration_s),
        "--client-control-base",
        str(control_base),
        "--no-auto-server",
        "--no-interactive",
    ]
    subprocess.run(sim_cmd, cwd=str(ROOT), check=True)


def wait_for(
    predicate,
    *,
    timeout_s: float,
    interval_s: float = 0.5,
    message: str,
):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval_s)
    raise AssertionError(f"{message}; last={last!r}")


def wait_run_status(
    base_url: str,
    run_id: str,
    *,
    statuses: tuple[str, ...] = ("complete",),
    timeout_s: float = 90.0,
) -> dict:
    def _check() -> dict | None:
        run = api_json(base_url, f"/api/history/{run_id}")
        status = str(run.get("status") or "")
        return run if status in statuses else None

    return wait_for(
        _check,
        timeout_s=timeout_s,
        interval_s=0.5,
        message=f"Run {run_id} did not reach statuses {statuses}",
    )


def history_run_ids(base_url: str) -> set[str]:
    return {str(item["run_id"]) for item in api_json(base_url, "/api/history").get("runs", [])}


def parse_export_zip(raw: bytes) -> tuple[dict, list[dict[str, str]], set[str]]:
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        names = set(archive.namelist())
        json_name = next(name for name in names if name.endswith(".json"))
        csv_name = next(name for name in names if name.endswith("_raw.csv"))
        run_json = json.loads(archive.read(json_name).decode("utf-8"))
        rows = list(csv.DictReader(io.StringIO(archive.read(csv_name).decode("utf-8"))))
    return run_json, rows, names
