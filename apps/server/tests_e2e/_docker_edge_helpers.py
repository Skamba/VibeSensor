"""Shared helpers for focused Docker E2E edge-case tests."""

from __future__ import annotations

from tests_e2e.e2e_helpers import (
    api_json,
    run_simulator,
    wait_run_status,
)

SHORT_RUN_DURATION_S = 0.8
FORBIDDEN_PLACEHOLDERS = (" null ", " none ", " nan ", " undefined ", "{{", "}}")


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
            base_url,
            f"/api/clients/{client['id']}/location",
            method="POST",
            body={"location_code": ""},
            expected_status=(200, 404),
        )
        api_json(
            base_url, f"/api/clients/{client['id']}", method="DELETE", expected_status=(200, 404)
        )


def _wait_complete(base_url: str, run_id: str) -> dict:
    return wait_run_status(base_url, run_id, statuses=("complete", "error"), timeout_s=120.0)


def _assert_no_placeholders(text: str) -> None:
    padded = f" {text} "
    for token in FORBIDDEN_PLACEHOLDERS:
        assert token not in padded


def _run_status_context(run: dict) -> str:
    return (
        f"run_id={run.get('run_id')} "
        f"status={run.get('status')} "
        f"sample_count={run.get('sample_count')} "
        f"error_message={run.get('error_message')!r}"
    )
