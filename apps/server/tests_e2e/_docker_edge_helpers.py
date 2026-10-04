"""Shared helpers for focused Docker E2E edge-case tests."""

from __future__ import annotations

from tests_e2e.e2e_helpers import (
    ANALYZABLE_SIM_DURATION_S,
    api_json,
    run_simulator,
    wait_run_status,
)

FORBIDDEN_PLACEHOLDERS = (" null ", " none ", " nan ", " undefined ", "{{", "}}")


def _simulate(
    e: dict[str, str],
    *,
    duration: float = ANALYZABLE_SIM_DURATION_S,
    count: int = 4,
    names: str | None = None,
) -> None:
    """Run the simulator; the default duration is long enough for post-analysis."""
    run_simulator(
        base_url=e["base_url"],
        sim_host=e["sim_host"],
        sim_data_port=e["sim_data_port"],
        sim_control_port=e["sim_control_port"],
        gps_port=e["sim_gps_port"],
        duration_s=duration,
        count=count,
        names=names or "front-left,front-right,rear-left,rear-right",
    )


def _cleanup_run(base_url: str, run_id: str) -> None:
    api_json(base_url, f"/api/history/{run_id}", method="DELETE", expected_status=(200, 404, 409))


def _wait_complete(base_url: str, run_id: str) -> dict:
    return wait_run_status(base_url, run_id, statuses=("complete",), timeout_s=120.0)


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
