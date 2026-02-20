"""
Covers E2E-1..E2E-8 user journeys in Docker full-suite CI.

Run locally via `make test-all` (uses tools/tests/run_full_suite.py harness).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.e2e

MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
LOCATION_CODES = (
    "front_left_wheel",
    "front_right_wheel",
    "rear_left_wheel",
    "rear_right_wheel",
)


def _api_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    expected_status: int | tuple[int, ...] = 200,
    timeout: int = 20,
) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = Request(f"{base_url}{path}", data=data, method=method, headers=headers)
    expected_statuses = (
        (expected_status,) if isinstance(expected_status, int) else tuple(expected_status)
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            assert resp.status in expected_statuses
            raw = resp.read()
    except HTTPError as exc:
        if exc.code not in expected_statuses:
            raise
        raw = exc.read()
    return json.loads(raw) if raw else {}


def _api_bytes(
    base_url: str,
    path: str,
    *,
    expected_status: int | tuple[int, ...] = 200,
    timeout: int = 30,
) -> tuple[bytes, str]:
    req = Request(f"{base_url}{path}")
    expected_statuses = (
        (expected_status,) if isinstance(expected_status, int) else tuple(expected_status)
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            assert resp.status in expected_statuses
            return resp.read(), str(resp.headers.get("Content-Type", ""))
    except HTTPError as exc:
        if exc.code not in expected_statuses:
            raise
        return exc.read(), str(exc.headers.get("Content-Type", ""))


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(filter(None, (page.extract_text() for page in reader.pages))).lower()


def _run_simulator(
    *,
    base_url: str,
    sim_host: str,
    sim_data_port: str,
    sim_control_port: str,
    duration_s: str,
    count: int = 4,
) -> None:
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
        "front-left,front-right,rear-left,rear-right",
        "--scenario",
        "one-wheel-mild",
        "--fault-wheel",
        "rear-left",
        "--speed-kmh",
        "0",
        "--duration",
        duration_s,
        "--no-auto-server",
        "--no-interactive",
    ]
    subprocess.run(sim_cmd, cwd=str(ROOT), check=True)


def _wait_run_complete(base_url: str, run_id: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run = _api_json(base_url, f"/api/history/{run_id}")
        if run.get("status") == "complete":
            return
        time.sleep(1.0)
    raise AssertionError(f"Run {run_id} did not complete in time")


def _circumference_m(width_mm: float, aspect_pct: float, rim_in: float) -> float:
    return math.pi * ((rim_in * 25.4 + 2.0 * (width_mm * (aspect_pct / 100.0))) / 1000.0)


def test_e2e_docker_user_journeys() -> None:
    base_url = os.environ["VIBESENSOR_BASE_URL"]
    sim_host = os.environ["VIBESENSOR_SIM_SERVER_HOST"]
    sim_data_port = os.environ["VIBESENSOR_SIM_DATA_PORT"]
    sim_control_port = os.environ["VIBESENSOR_SIM_CONTROL_PORT"]
    sim_duration = os.environ["VIBESENSOR_SIM_DURATION"]

    cars_before = _api_json(base_url, "/api/settings/cars")
    original_active_car_id = str(cars_before["activeCarId"])
    speed_source_before = _api_json(base_url, "/api/settings/speed-source")
    language_before = _api_json(base_url, "/api/settings/language")["language"]

    created_car_id: str | None = None
    created_run_ids: list[str] = []
    seen_client_ids: list[str] = []
    seen_sensor_macs: list[str] = []

    try:
        # Ensure deterministic client count for E2E-1 assertions.
        existing_clients = _api_json(base_url, "/api/clients")["clients"]
        for client in existing_clients:
            _api_json(base_url, f"/api/clients/{client['id']}", method="DELETE")

        # E2E-1: Sensors appear as clients.
        _run_simulator(
            base_url=base_url,
            sim_host=sim_host,
            sim_data_port=sim_data_port,
            sim_control_port=sim_control_port,
            duration_s=sim_duration,
            count=4,
        )
        clients = _api_json(base_url, "/api/clients")["clients"]
        assert len(clients) == 4
        for client in clients:
            assert client.get("id")
            mac = str(client.get("mac_address") or "")
            assert MAC_RE.match(mac)
        seen_client_ids = sorted(str(client["id"]) for client in clients)

        # E2E-2: Assign locations and enforce uniqueness.
        locations = _api_json(base_url, "/api/client-locations")["locations"]
        location_labels = {entry["code"]: entry["label"] for entry in locations}
        for client_id, code in zip(seen_client_ids, LOCATION_CODES, strict=True):
            assigned = _api_json(
                base_url,
                f"/api/clients/{client_id}/location",
                method="POST",
                body={"location_code": code},
            )
            assert assigned["id"] == client_id
            assert assigned["location_code"] == code
            assert assigned["name"] == location_labels[code]
            assert MAC_RE.match(str(assigned.get("mac_address") or ""))
            seen_sensor_macs.append(str(assigned["mac_address"]))

        _api_json(
            base_url,
            f"/api/clients/{seen_client_ids[1]}/location",
            method="POST",
            body={"location_code": LOCATION_CODES[0]},
            expected_status=409,
        )

        sensors_by_mac = _api_json(base_url, "/api/settings/sensors")["sensorsByMac"]
        for mac, code in zip(seen_sensor_macs, LOCATION_CODES, strict=True):
            normalized = mac.replace(":", "").lower()
            assert sensors_by_mac[normalized]["location"] == code

        # E2E-3: Create a car profile and make it active.
        baseline_car_ids = {str(car["id"]) for car in cars_before["cars"]}
        car_aspects = {
            "tire_width_mm": 245.0,
            "tire_aspect_pct": 40.0,
            "rim_in": 19.0,
            "final_drive_ratio": 3.15,
            "current_gear_ratio": 0.91,
        }
        cars_after_add = _api_json(
            base_url,
            "/api/settings/cars",
            method="POST",
            body={"name": "E2E Journey Car", "type": "hatchback", "aspects": car_aspects},
        )
        created_car = next(
            car for car in cars_after_add["cars"] if str(car["id"]) not in baseline_car_ids
        )
        created_car_id = str(created_car["id"])
        _api_json(
            base_url,
            "/api/settings/cars/active",
            method="POST",
            body={"carId": created_car_id},
        )
        cars_active = _api_json(base_url, "/api/settings/cars")
        assert cars_active["activeCarId"] == created_car_id
        active_car = next(car for car in cars_active["cars"] if str(car["id"]) == created_car_id)
        for key, value in car_aspects.items():
            assert float(active_car["aspects"][key]) == pytest.approx(value)
        analysis_settings = _api_json(base_url, "/api/analysis-settings")
        for key, value in car_aspects.items():
            assert float(analysis_settings[key]) == pytest.approx(value)

        # E2E-4: Changed wheel size appears in run metadata.
        updated_tire = {"tire_width_mm": 275.0, "tire_aspect_pct": 35.0, "rim_in": 20.0}
        _api_json(
            base_url,
            f"/api/settings/cars/{created_car_id}",
            method="PUT",
            body={"aspects": updated_tire},
        )
        start_1 = _api_json(base_url, "/api/logging/start", method="POST")
        run_id_1 = str(start_1["run_id"])
        _run_simulator(
            base_url=base_url,
            sim_host=sim_host,
            sim_data_port=sim_data_port,
            sim_control_port=sim_control_port,
            duration_s=sim_duration,
            count=4,
        )
        _api_json(base_url, "/api/logging/stop", method="POST")
        _wait_run_complete(base_url, run_id_1)
        created_run_ids.append(run_id_1)
        run_1 = _api_json(base_url, f"/api/history/{run_id_1}")
        metadata_1 = run_1["metadata"]
        for key, value in updated_tire.items():
            assert float(metadata_1[key]) == pytest.approx(value)
        expected_circ = _circumference_m(
            updated_tire["tire_width_mm"], updated_tire["tire_aspect_pct"], updated_tire["rim_in"]
        )
        assert float(metadata_1["tire_circumference_m"]) == pytest.approx(expected_circ, abs=1e-6)

        # E2E-5/6/7: Manual speed, ZIP export format, and delete semantics.
        _api_json(
            base_url,
            "/api/settings/speed-source",
            method="POST",
            body={"speedSource": "manual", "manualSpeedKph": 80},
        )
        speed_now = _api_json(base_url, "/api/speed-override")
        assert float(speed_now["speed_kmh"]) == pytest.approx(80.0)

        start_2 = _api_json(base_url, "/api/logging/start", method="POST")
        run_id_2 = str(start_2["run_id"])
        _run_simulator(
            base_url=base_url,
            sim_host=sim_host,
            sim_data_port=sim_data_port,
            sim_control_port=sim_control_port,
            duration_s=sim_duration,
            count=4,
        )
        _api_json(base_url, "/api/logging/stop", method="POST")
        _wait_run_complete(base_url, run_id_2)
        created_run_ids.append(run_id_2)

        export_bytes, export_content_type = _api_bytes(base_url, f"/api/history/{run_id_2}/export")
        assert export_content_type.startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(export_bytes), "r") as archive:
            names = set(archive.namelist())
            assert names == {f"{run_id_2}.json", f"{run_id_2}_raw.csv"}
            run_details = json.loads(archive.read(f"{run_id_2}.json").decode("utf-8"))
            assert str(run_details.get("run_id")) == run_id_2
            rows = list(
                csv.DictReader(io.StringIO(archive.read(f"{run_id_2}_raw.csv").decode("utf-8")))
            )
        assert rows
        speed_values = [
            float(row["speed_kmh"]) for row in rows if row.get("speed_kmh") not in (None, "")
        ]
        assert len(speed_values) >= 10
        close_to_80 = [value for value in speed_values if abs(value - 80.0) <= 2.0]
        assert len(close_to_80) >= max(5, int(len(speed_values) * 0.8))

        deleted = _api_json(base_url, f"/api/history/{run_id_2}", method="DELETE")
        assert deleted == {"run_id": run_id_2, "status": "deleted"}
        created_run_ids.remove(run_id_2)
        history_after_delete = _api_json(base_url, "/api/history")["runs"]
        assert all(str(run["run_id"]) != run_id_2 for run in history_after_delete)
        _api_json(base_url, f"/api/history/{run_id_2}", expected_status=404)
        _api_json(base_url, f"/api/history/{run_id_2}/insights", expected_status=404)
        _api_bytes(base_url, f"/api/history/{run_id_2}/report.pdf", expected_status=404)

        # E2E-8: Language differences in insights and PDF report.
        _api_json(base_url, "/api/settings/language", method="POST", body={"language": "nl"})
        start_3 = _api_json(base_url, "/api/logging/start", method="POST")
        run_id_3 = str(start_3["run_id"])
        _run_simulator(
            base_url=base_url,
            sim_host=sim_host,
            sim_data_port=sim_data_port,
            sim_control_port=sim_control_port,
            duration_s=sim_duration,
            count=4,
        )
        _api_json(base_url, "/api/logging/stop", method="POST")
        _wait_run_complete(base_url, run_id_3)
        created_run_ids.append(run_id_3)

        insights_nl = _api_json(base_url, f"/api/history/{run_id_3}/insights?lang=nl")
        insights_en = _api_json(base_url, f"/api/history/{run_id_3}/insights?lang=en")
        checks_nl = {str(item.get("check")) for item in insights_nl.get("run_suitability", [])}
        checks_en = {str(item.get("check")) for item in insights_en.get("run_suitability", [])}
        assert "Snelheidsvariatie" in checks_nl
        assert "Speed variation" in checks_en

        pdf_nl, type_nl = _api_bytes(base_url, f"/api/history/{run_id_3}/report.pdf?lang=nl")
        pdf_en, type_en = _api_bytes(base_url, f"/api/history/{run_id_3}/report.pdf?lang=en")
        assert type_nl.startswith("application/pdf")
        assert type_en.startswith("application/pdf")
        text_nl = _pdf_text(pdf_nl)
        text_en = _pdf_text(pdf_en)
        assert "diagnostisch werkblad" in text_nl
        assert "diagnostic worksheet" in text_en

    finally:
        for run_id in list(created_run_ids):
            _api_json(
                base_url,
                f"/api/history/{run_id}",
                method="DELETE",
                expected_status=(200, 404),
            )
        for sensor_mac in seen_sensor_macs:
            _api_json(
                base_url,
                f"/api/settings/sensors/{sensor_mac}",
                method="DELETE",
                expected_status=(200, 404),
            )
        for client_id in seen_client_ids:
            _api_json(
                base_url,
                f"/api/clients/{client_id}",
                method="DELETE",
                expected_status=(200, 404),
            )
        _api_json(
            base_url,
            "/api/settings/speed-source",
            method="POST",
            body={
                "speedSource": speed_source_before["speedSource"],
                "manualSpeedKph": speed_source_before["manualSpeedKph"],
            },
        )
        _api_json(
            base_url,
            "/api/settings/language",
            method="POST",
            body={"language": language_before},
        )
        if created_car_id is not None:
            _api_json(
                base_url,
                "/api/settings/cars/active",
                method="POST",
                body={"carId": original_active_car_id},
            )
            _api_json(
                base_url,
                f"/api/settings/cars/{created_car_id}",
                method="DELETE",
                expected_status=(200, 404),
            )
