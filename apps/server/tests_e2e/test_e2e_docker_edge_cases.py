from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest

from .e2e_helpers import (
    api_bytes,
    api_json,
    history_run_ids,
    parse_export_zip,
    pdf_text,
    run_simulator,
    wait_for,
    wait_run_status,
)

pytestmark = pytest.mark.e2e
SHORT_RUN_DURATION_S = 0.8
FORBIDDEN_PLACEHOLDERS = (" null ", " none ", " nan ", " undefined ", "{{", "}}")


@pytest.fixture
def e2e_env() -> dict[str, str]:
    return {
        "base_url": os.environ["VIBESENSOR_BASE_URL"],
        "sim_host": os.environ["VIBESENSOR_SIM_SERVER_HOST"],
        "sim_data_port": os.environ["VIBESENSOR_SIM_DATA_PORT"],
        "sim_control_port": os.environ["VIBESENSOR_SIM_CONTROL_PORT"],
        "sim_duration": os.environ["VIBESENSOR_SIM_DURATION"],
        "sim_duration_long": os.environ.get("VIBESENSOR_SIM_DURATION_LONG", "20"),
    }


def _simulate(
    e: dict[str, str], *, duration: float | None = None, count: int = 4, names: str | None = None
) -> None:
    run_simulator(
        base_url=e["base_url"],
        sim_host=e["sim_host"],
        sim_data_port=e["sim_data_port"],
        sim_control_port=e["sim_control_port"],
        duration_s=duration if duration is not None else float(e["sim_duration"]),
        count=count,
        names=names or "front-left,front-right,rear-left,rear-right",
    )


def _cleanup_run(base_url: str, run_id: str) -> None:
    api_json(base_url, f"/api/history/{run_id}", method="DELETE", expected_status=(200, 404, 409))


def _cleanup_clients(base_url: str) -> None:
    for client in api_json(base_url, "/api/clients").get("clients", []):
        api_json(
            base_url, f"/api/clients/{client['id']}", method="DELETE", expected_status=(200, 404)
        )


def _wait_complete(base_url: str, run_id: str) -> dict:
    return wait_run_status(base_url, run_id, statuses=("complete", "error"), timeout_s=120.0)


def _assert_no_placeholders(text: str) -> None:
    padded = f" {text} "
    for token in FORBIDDEN_PLACEHOLDERS:
        assert token not in padded


def test_logging_start_while_recording_rollover(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_ids: list[str] = []
    try:
        first = api_json(base, "/api/logging/start", method="POST")
        run_1 = str(first["run_id"])
        run_ids.append(run_1)
        _simulate(e2e_env, duration=3.0)

        second = api_json(base, "/api/logging/start", method="POST")
        run_2 = str(second["run_id"])
        run_ids.append(run_2)
        assert run_2 != run_1

        wait_for(
            lambda: (
                api_json(base, f"/api/history/{run_1}")
                if api_json(base, f"/api/history/{run_1}").get("status")
                in {"analyzing", "complete", "error"}
                else None
            ),
            timeout_s=30,
            message=f"first rollover run {run_1} did not finalize",
        )

        _simulate(e2e_env, duration=3.0)
        api_json(base, "/api/logging/stop", method="POST")

        final_1 = _wait_complete(base, run_1)
        final_2 = _wait_complete(base, run_2)
        assert final_1["status"] == "complete"
        assert final_2["status"] == "complete"

        for run_id in (run_1, run_2):
            insights = api_json(base, f"/api/history/{run_id}/insights")
            assert insights.get("findings"), f"expected findings for rollover run {run_id}"
    finally:
        api_json(base, "/api/logging/stop", method="POST", expected_status=(200,))
        for run_id in run_ids:
            _cleanup_run(base, run_id)


def test_logging_stop_when_idle_noop(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    before = history_run_ids(base)
    stopped = api_json(base, "/api/logging/stop", method="POST")
    assert stopped["enabled"] is False
    assert stopped["run_id"] is None
    assert history_run_ids(base) == before


def test_delete_active_run_returns_409_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = ""
    try:
        run_id = str(api_json(base, "/api/logging/start", method="POST")["run_id"])
        _simulate(e2e_env, duration=3.0)
        err = api_json(base, f"/api/history/{run_id}", method="DELETE", expected_status=409)
        assert "active run" in str(err.get("detail", "")).lower()
    finally:
        api_json(base, "/api/logging/stop", method="POST")
        if run_id:
            _wait_complete(base, run_id)
            _cleanup_run(base, run_id)


def test_report_and_insights_not_ready_states(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = str(api_json(base, "/api/logging/start", method="POST")["run_id"])
    try:
        _simulate(e2e_env, duration=2.5)
        insights_while = api_json(base, f"/api/history/{run_id}/insights", expected_status=422)
        assert "analysis" in str(insights_while.get("detail", "")).lower()

        pdf_while = api_bytes(base, f"/api/history/{run_id}/report.pdf", expected_status=422)
        assert b"analysis" in pdf_while.body.lower()

        api_json(base, "/api/logging/stop", method="POST")
        immediate = api_json(base, f"/api/history/{run_id}/insights", expected_status=(200, 422))
        if immediate.get("status") == "analyzing":
            pass
        elif immediate.get("findings"):
            assert isinstance(immediate["findings"], list)
        else:
            assert "analysis" in str(immediate.get("detail", "")).lower()

        complete = _wait_complete(base, run_id)
        assert complete["status"] == "complete"
        insights = api_json(base, f"/api/history/{run_id}/insights")
        assert insights.get("findings")
    finally:
        api_json(base, "/api/logging/stop", method="POST")
        _cleanup_run(base, run_id)


def test_unknown_run_404_matrix(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = f"does-not-exist-{uuid.uuid4().hex}"
    api_json(base, f"/api/history/{run_id}", expected_status=404)
    api_json(base, f"/api/history/{run_id}/insights", expected_status=404)
    api_bytes(base, f"/api/history/{run_id}/report.pdf", expected_status=404)
    api_bytes(base, f"/api/history/{run_id}/export", expected_status=404)
    api_json(base, f"/api/history/{run_id}", method="DELETE", expected_status=404)


def test_client_location_invalid_input_matrix(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    _cleanup_clients(base)
    _simulate(e2e_env, duration=2.0, count=2, names="front-left,front-right")
    clients = sorted(api_json(base, "/api/clients")["clients"], key=lambda c: str(c["id"]))
    assert len(clients) >= 2

    c1 = str(clients[0]["id"])
    c2 = str(clients[1]["id"])
    macs = [str(clients[0]["mac_address"]), str(clients[1]["mac_address"])]
    try:
        api_json(
            base,
            "/api/clients/not-a-client/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
            expected_status=400,
        )
        api_json(
            base,
            "/api/clients/025a000000ff/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
            expected_status=404,
        )
        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "nowhere"},
            expected_status=400,
        )

        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_right_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
            expected_status=409,
        )
    finally:
        for mac in macs:
            api_json(
                base, f"/api/settings/sensors/{mac}", method="DELETE", expected_status=(200, 404)
            )
        _cleanup_clients(base)


def test_location_reassignment_releases_previous_slot(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    _cleanup_clients(base)
    _simulate(e2e_env, duration=2.0, count=2, names="front-left,front-right")
    clients = sorted(api_json(base, "/api/clients")["clients"], key=lambda c: str(c["id"]))
    c1 = str(clients[0]["id"])
    c2 = str(clients[1]["id"])
    mac_1 = str(clients[0]["mac_address"])
    mac_2 = str(clients[1]["mac_address"])
    try:
        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_right_wheel"},
        )
        api_json(
            base,
            f"/api/clients/{c1}/location",
            method="POST",
            body={"location_code": "rear_left_wheel"},
        )
        moved = api_json(
            base,
            f"/api/clients/{c2}/location",
            method="POST",
            body={"location_code": "front_left_wheel"},
        )
        assert moved["location_code"] == "front_left_wheel"

        sensors = api_json(base, "/api/settings/sensors")["sensorsByMac"]
        assert sensors[mac_1.replace(":", "")]["location"] == "rear_left_wheel"
        assert sensors[mac_2.replace(":", "")]["location"] == "front_left_wheel"
    finally:
        for mac in (mac_1, mac_2):
            api_json(
                base, f"/api/settings/sensors/{mac}", method="DELETE", expected_status=(200, 404)
            )
        _cleanup_clients(base)


def test_sensor_settings_crud_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    _simulate(e2e_env, duration=2.0, count=1, names="front-left")
    client = api_json(base, "/api/clients")["clients"][0]
    mac = str(client["mac_address"])
    sid = mac.replace(":", "")
    try:
        api_json(
            base,
            f"/api/settings/sensors/{mac}",
            method="POST",
            body={"name": "E2E Sensor", "location": "rear_left_wheel"},
        )
        sensors = api_json(base, "/api/settings/sensors")["sensorsByMac"]
        assert sensors[sid]["name"] == "E2E Sensor"
        assert sensors[sid]["location"] == "rear_left_wheel"

        api_json(base, f"/api/settings/sensors/{mac}", method="DELETE")
        api_json(base, f"/api/settings/sensors/{mac}", method="DELETE", expected_status=404)
        api_json(base, "/api/settings/sensors/not-a-mac", method="DELETE", expected_status=400)
    finally:
        _cleanup_clients(base)


def test_car_crud_edge_cases_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    cars_before = api_json(base, "/api/settings/cars")
    original_active = str(cars_before["activeCarId"])

    api_json(
        base,
        "/api/settings/cars",
        method="POST",
        body={
            "name": "Edge A",
            "type": "sedan",
            "aspects": {"tire_width_mm": 255, "tire_aspect_pct": 40, "rim_in": 19},
        },
    )
    car_b = api_json(
        base,
        "/api/settings/cars",
        method="POST",
        body={
            "name": "Edge B",
            "type": "sedan",
            "aspects": {"tire_width_mm": 265, "tire_aspect_pct": 35, "rim_in": 20},
        },
    )
    ids_after = {str(c["id"]) for c in car_b["cars"]}
    ids_before = {str(c["id"]) for c in cars_before["cars"]}
    created_ids = sorted(ids_after - ids_before)
    assert len(created_ids) == 2

    try:
        api_json(
            base,
            "/api/settings/cars/active",
            method="POST",
            body={"carId": "missing-car"},
            expected_status=404,
        )

        active_target = created_ids[0]
        api_json(base, "/api/settings/cars/active", method="POST", body={"carId": active_target})
        api_json(base, f"/api/settings/cars/{active_target}", method="DELETE")
        after_delete = api_json(base, "/api/settings/cars")
        assert after_delete["activeCarId"] != active_target

        while len(api_json(base, "/api/settings/cars")["cars"]) > 1:
            snapshot = api_json(base, "/api/settings/cars")
            active = str(snapshot["activeCarId"])
            victim = next(str(c["id"]) for c in snapshot["cars"] if str(c["id"]) != active)
            api_json(base, f"/api/settings/cars/{victim}", method="DELETE")
        lone = api_json(base, "/api/settings/cars")
        lone_id = str(lone["activeCarId"])
        api_json(base, f"/api/settings/cars/{lone_id}", method="DELETE", expected_status=400)

        analysis = api_json(base, "/api/analysis-settings")
        active_car = next(c for c in lone["cars"] if str(c["id"]) == lone_id)
        assert float(analysis["tire_width_mm"]) == pytest.approx(
            float(active_car["aspects"]["tire_width_mm"])
        )
    finally:
        current = api_json(base, "/api/settings/cars")
        remaining_ids = {str(c["id"]) for c in current["cars"]}
        for car_id in sorted(remaining_ids):
            if car_id != original_active:
                api_json(
                    base,
                    f"/api/settings/cars/{car_id}",
                    method="DELETE",
                    expected_status=(200, 400, 404),
                )
        api_json(
            base,
            "/api/settings/cars/active",
            method="POST",
            body={"carId": original_active},
            expected_status=(200, 404),
        )


def test_speed_source_transitions_and_invalid_values(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    before = api_json(base, "/api/settings/speed-source")
    run_id = ""
    try:
        gps = api_json(
            base, "/api/settings/speed-source", method="POST", body={"speedSource": "gps"}
        )
        assert gps["speedSource"] == "gps"

        manual = api_json(
            base,
            "/api/settings/speed-source",
            method="POST",
            body={"speedSource": "manual", "manualSpeedKph": 77},
        )
        assert manual["speedSource"] == "manual"
        assert float(manual["manualSpeedKph"]) == pytest.approx(77.0)

        obd2 = api_json(
            base, "/api/settings/speed-source", method="POST", body={"speedSource": "obd2"}
        )
        assert obd2["speedSource"] == "obd2"

        api_json(
            base,
            "/api/settings/speed-source",
            method="POST",
            body={"speedSource": "manual", "manualSpeedKph": 77},
        )
        run_id = str(api_json(base, "/api/logging/start", method="POST")["run_id"])
        _simulate(e2e_env, duration=3.0)
        api_json(base, "/api/logging/stop", method="POST")
        complete = _wait_complete(base, run_id)
        assert complete["status"] == "complete"

        export_resp = api_bytes(base, f"/api/history/{run_id}/export")
        _, rows, _ = parse_export_zip(export_resp.body)
        speed_values = [float(r["speed_kmh"]) for r in rows if r.get("speed_kmh") not in (None, "")]
        assert speed_values
        assert sum(1 for v in speed_values if abs(v - 77.0) <= 2.0) >= max(
            3, int(len(speed_values) * 0.75)
        )

        invalid = api_json(
            base,
            "/api/settings/speed-source",
            method="POST",
            body={"speedSource": "invalid", "manualSpeedKph": 77},
        )
        assert invalid["speedSource"] == "manual"
        assert float(invalid["manualSpeedKph"]) == pytest.approx(77.0)
    finally:
        api_json(base, "/api/logging/stop", method="POST")
        if run_id:
            _cleanup_run(base, run_id)
        api_json(
            base,
            "/api/settings/speed-source",
            method="POST",
            body={"speedSource": before["speedSource"], "manualSpeedKph": before["manualSpeedKph"]},
        )


def test_language_and_speed_unit_validation_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    language_before = api_json(base, "/api/settings/language")["language"]
    unit_before = api_json(base, "/api/settings/speed-unit")["speedUnit"]
    run_id = ""
    try:
        assert (
            api_json(base, "/api/settings/language", method="POST", body={"language": "en"})[
                "language"
            ]
            == "en"
        )
        assert (
            api_json(base, "/api/settings/language", method="POST", body={"language": "nl"})[
                "language"
            ]
            == "nl"
        )
        assert (
            api_json(base, "/api/settings/speed-unit", method="POST", body={"speedUnit": "kmh"})[
                "speedUnit"
            ]
            == "kmh"
        )
        assert (
            api_json(base, "/api/settings/speed-unit", method="POST", body={"speedUnit": "mps"})[
                "speedUnit"
            ]
            == "mps"
        )

        api_json(
            base,
            "/api/settings/language",
            method="POST",
            body={"language": "de"},
            expected_status=422,
        )
        api_json(
            base,
            "/api/settings/speed-unit",
            method="POST",
            body={"speedUnit": "mph"},
            expected_status=422,
        )

        run_id = str(api_json(base, "/api/logging/start", method="POST")["run_id"])
        _simulate(e2e_env, duration=3.0)
        api_json(base, "/api/logging/stop", method="POST")
        _wait_complete(base, run_id)

        insights_en = api_json(base, f"/api/history/{run_id}/insights?lang=en")
        insights_nl = api_json(base, f"/api/history/{run_id}/insights?lang=nl")
        checks_en = {str(item.get("check")) for item in insights_en.get("run_suitability", [])}
        checks_nl = {str(item.get("check")) for item in insights_nl.get("run_suitability", [])}
        assert "Speed variation" in checks_en
        assert "Snelheidsvariatie" in checks_nl

        if insights_en.get("findings") and insights_nl.get("findings"):
            en_first = insights_en["findings"][0]
            nl_first = insights_nl["findings"][0]
            assert en_first.get("suspected_source") == nl_first.get("suspected_source")
            assert float(en_first.get("confidence", 0.0)) == pytest.approx(
                float(nl_first.get("confidence", 0.0)), abs=1e-6
            )
    finally:
        api_json(base, "/api/logging/stop", method="POST")
        if run_id:
            _cleanup_run(base, run_id)
        api_json(base, "/api/settings/language", method="POST", body={"language": language_before})
        api_json(base, "/api/settings/speed-unit", method="POST", body={"speedUnit": unit_before})


def test_no_data_or_short_run_behavior_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    before = history_run_ids(base)

    first = api_json(base, "/api/logging/start", method="POST")
    run_empty = str(first["run_id"])
    api_json(base, "/api/logging/stop", method="POST")
    after_empty = history_run_ids(base)
    assert run_empty not in after_empty
    assert after_empty == before

    second = api_json(base, "/api/logging/start", method="POST")
    run_short = str(second["run_id"])
    _simulate(e2e_env, duration=SHORT_RUN_DURATION_S)
    api_json(base, "/api/logging/stop", method="POST")

    wait_for(
        lambda: run_short in history_run_ids(base),
        timeout_s=20,
        message=f"short run {run_short} did not appear",
    )
    run = _wait_complete(base, run_short)
    assert run["status"] in {"complete", "error"}
    if run["status"] == "complete":
        pdf = api_bytes(base, f"/api/history/{run_short}/report.pdf")
        assert pdf.body.startswith(b"%PDF-")
    _cleanup_run(base, run_short)


def test_reduced_sensor_count_run_still_reports(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = str(api_json(base, "/api/logging/start", method="POST")["run_id"])
    try:
        _simulate(e2e_env, duration=3.0, count=2, names="front-left,rear-left")
        api_json(base, "/api/logging/stop", method="POST")
        run = _wait_complete(base, run_id)
        assert run["status"] == "complete"

        insights = api_json(base, f"/api/history/{run_id}/insights")
        assert insights.get("findings")

        export_resp = api_bytes(base, f"/api/history/{run_id}/export")
        _, rows, _ = parse_export_zip(export_resp.body)
        assert rows

        pdf_resp = api_bytes(base, f"/api/history/{run_id}/report.pdf")
        text = pdf_text(pdf_resp.body)
        assert "diagnostic worksheet" in text
        _assert_no_placeholders(text)
    finally:
        api_json(base, "/api/logging/stop", method="POST")
        _cleanup_run(base, run_id)


def test_export_history_consistency_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = str(api_json(base, "/api/logging/start", method="POST")["run_id"])
    try:
        _simulate(e2e_env, duration=3.0)
        api_json(base, "/api/logging/stop", method="POST")
        detail = _wait_complete(base, run_id)
        summary_rows = api_json(base, "/api/history")["runs"]
        summary = next(item for item in summary_rows if str(item["run_id"]) == run_id)

        export_resp = api_bytes(base, f"/api/history/{run_id}/export")
        assert str(export_resp.headers.get("content-type", "")).startswith("application/zip")
        assert f"{run_id}.zip" in str(export_resp.headers.get("content-disposition", ""))

        export_json, rows, names = parse_export_zip(export_resp.body)
        assert names == {f"{run_id}.json", f"{run_id}_raw.csv"}
        assert str(export_json.get("run_id")) == run_id
        assert int(export_json.get("sample_count", -1)) == len(rows)
        assert int(summary.get("sample_count", -1)) == len(rows)
        assert int(detail.get("sample_count", -1)) == len(rows)

        assert rows
        expected_columns = {"timestamp_utc", "t_s", "client_id", "speed_kmh"}
        assert expected_columns.issubset(set(rows[0].keys()))

        parsed = []
        for row in rows:
            ts = str(row["timestamp_utc"]).replace("Z", "+00:00")
            parsed.append(datetime.fromisoformat(ts))
        assert all(parsed[i] <= parsed[i + 1] for i in range(len(parsed) - 1))
    finally:
        api_json(base, "/api/logging/stop", method="POST")
        _cleanup_run(base, run_id)


@pytest.mark.long_sim
def test_full_pdf_report_20s_accuracy_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    duration_long = float(e2e_env["sim_duration_long"])
    run_id = str(api_json(base, "/api/logging/start", method="POST")["run_id"])
    try:
        _simulate(e2e_env, duration=duration_long, count=4)
        api_json(base, "/api/logging/stop", method="POST")
        run = _wait_complete(base, run_id)
        assert run["status"] == "complete"

        detail = api_json(base, f"/api/history/{run_id}")
        insights = api_json(base, f"/api/history/{run_id}/insights?lang=en")
        export_resp = api_bytes(base, f"/api/history/{run_id}/export")
        export_json, rows, _ = parse_export_zip(export_resp.body)
        pdf_resp = api_bytes(base, f"/api/history/{run_id}/report.pdf?lang=en")
        text = " ".join(pdf_text(pdf_resp.body).split())

        for required in (
            "diagnostic worksheet",
            "observed signature",
            "systems with findings",
            "next steps",
            "data trust",
        ):
            assert required in text, f"missing PDF section: {required}"

        metadata = detail["metadata"]
        car_name = str(metadata.get("car_name") or "").strip().lower()
        if car_name:
            assert car_name in text
        assert run_id.lower() in text

        findings = [
            f
            for f in insights.get("findings", [])
            if not str(f.get("finding_id", "")).startswith("REF_")
        ]
        assert findings
        primary = findings[0]
        primary_source = str(primary.get("suspected_source") or "").replace("/", " / ").lower()
        source_label = {
            "wheel/tire": "wheel / tire",
            "driveline": "driveline",
            "engine": "engine",
            "unknown_resonance": "unknown",
        }.get(str(primary.get("suspected_source") or "").lower(), primary_source)
        assert source_label in text or source_label.replace(" ", "") in text.replace(" ", "")

        strongest = str(primary.get("strongest_location") or "").lower().replace("-", " ")
        if strongest:
            normalized_text = text.replace(" ", "")
            strongest_token = strongest.replace(" ", "")
            assert (
                strongest in text
                or strongest_token in normalized_text
                or "unknown" in text
                or "not available" in text
            )

        top_causes = [c for c in insights.get("top_causes", []) if isinstance(c, dict)]
        assert top_causes
        top_source = str(top_causes[0].get("source") or "").lower()
        top_source_label = {
            "wheel/tire": "wheel / tire",
            "driveline": "driveline",
            "engine": "engine",
            "unknown_resonance": "unknown",
        }.get(top_source, top_source.replace("/", " / "))
        assert top_source_label in text

        analysis = detail.get("analysis") or {}
        sensor_rows = [
            r for r in analysis.get("sensor_intensity_by_location", []) if isinstance(r, dict)
        ]
        assert sensor_rows
        assert len(rows) == int(export_json.get("sample_count", -1))

        fft = analysis.get("plots", {}).get("fft_spectrum", [])
        if fft:
            top_fft = max(
                fft,
                key=lambda item: float(item[1] if isinstance(item, list) else item.get("amp") or 0),
            )
            peak_hz = float(top_fft[0] if isinstance(top_fft, list) else top_fft.get("hz") or 0)
            assert any(token in text for token in (f"{peak_hz:.1f}", f"{peak_hz:.2f}"))

        _assert_no_placeholders(text)
    finally:
        api_json(base, "/api/logging/stop", method="POST")
        _cleanup_run(base, run_id)
