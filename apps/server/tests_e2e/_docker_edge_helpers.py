"""Shared helpers for focused Docker E2E edge-case tests."""

from __future__ import annotations

import time
from typing import Final

from tests_e2e.e2e_helpers import (
    api_json,
    run_simulator,
    wait_for,
    wait_run_status,
)
from vibesensor.adapters.simulator.sim_client import make_client_id

SHORT_RUN_DURATION_S = 0.8
FORBIDDEN_PLACEHOLDERS = (" null ", " none ", " nan ", " undefined ", "{{", "}}")
DEFAULT_SIMULATOR_NAMES: Final[tuple[str, ...]] = (
    "front-left",
    "front-right",
    "rear-left",
    "rear-right",
)
SIMULATOR_LOCATION_BY_NAME: Final[dict[str, str]] = {
    "front-left": "front_left_wheel",
    "front-right": "front_right_wheel",
    "rear-left": "rear_left_wheel",
    "rear-right": "rear_right_wheel",
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


def _delete_clients_preserving_sensor_settings(base_url: str) -> None:
    for client in api_json(base_url, "/api/clients").get("clients", []):
        api_json(
            base_url, f"/api/clients/{client['id']}", method="DELETE", expected_status=(200, 404)
        )


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


def _prepare_simulator_locations(
    e: dict[str, str],
    *,
    count: int = 4,
    names: str | None = None,
    preflight_duration_s: float = 2.0,
) -> None:
    """Persist canonical location settings for deterministic simulator clients.

    The simulator client ids are deterministic by index.  Run a short preflight
    so the public client-location endpoint can assign settings, then delete the
    runtime records so the real capture starts with fresh sequence/dedup state.
    """

    name_list = _simulator_names(names, count=count)
    assignments = [
        (make_client_id(index + 1).hex(), SIMULATOR_LOCATION_BY_NAME[name])
        for index, name in enumerate(name_list)
        if name in SIMULATOR_LOCATION_BY_NAME
    ]
    if not assignments:
        return

    base_url = e["base_url"]
    run_simulator(
        base_url=base_url,
        sim_host=e["sim_host"],
        sim_data_port=e["sim_data_port"],
        sim_control_port=e["sim_control_port"],
        duration_s=preflight_duration_s,
        count=count,
        names=",".join(name_list),
        scenario="road-fixed",
    )
    expected_ids = {client_id for client_id, _ in assignments}
    wait_for(
        lambda: expected_ids
        if expected_ids
        <= {str(client["id"]) for client in api_json(base_url, "/api/clients").get("clients", [])}
        else None,
        timeout_s=5.0,
        interval_s=0.25,
        message="simulator clients did not register before location assignment",
    )

    for client_id, _location_code in assignments:
        api_json(
            base_url,
            f"/api/clients/{client_id}/location",
            method="POST",
            body={"location_code": ""},
        )
    for client_id, location_code in assignments:
        api_json(
            base_url,
            f"/api/clients/{client_id}/location",
            method="POST",
            body={"location_code": location_code},
        )

    _delete_clients_preserving_sensor_settings(base_url)
    time.sleep(0.5)
    _delete_clients_preserving_sensor_settings(base_url)
    wait_for(
        lambda: not api_json(base_url, "/api/clients").get("clients"),
        timeout_s=3.0,
        interval_s=0.25,
        message="preflight simulator clients did not clear before capture",
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


def _pdf_mentions_frequency(text: str, hz: float) -> bool:
    """Return True when PDF text mentions *hz* with rounding tolerance.

    PDF rendering can round frequencies differently (1–2 decimals, integer, or
    locale decimal comma). Accepts both:
    - adjacent-unit form (additional observations): "13.0 hz"
    - bare decimal form (peaks table column values): "13.0"
    """
    if hz <= 0:
        return False
    lowered = text.lower()
    compact = lowered.replace(" ", "")

    tokens: set[str] = {
        f"{hz:.2f}",
        f"{hz:.1f}",
        f"{hz:.0f}",
        f"{round(hz)}",
    }
    rounded_1 = round(hz, 1)
    for delta in (-0.2, -0.1, 0.0, 0.1, 0.2):
        value = rounded_1 + delta
        tokens.add(f"{value:.2f}")
        tokens.add(f"{value:.1f}")
    tokens_with_comma = {t.replace(".", ",") for t in tokens if "." in t}
    all_tokens = tokens | tokens_with_comma

    # Adjacent-unit check: "13.0 hz" or "13.0hz" (additional observations section)
    if any((f"{token} hz" in lowered) or (f"{token}hz" in compact) for token in all_tokens):
        return True

    # Bare decimal check: peaks table renders frequencies without a unit suffix.
    # Only match period-decimal tokens (from the original tokens set, not comma
    # variants) to stay locale-neutral and avoid colliding with "13%".
    return any(token in lowered for token in tokens if "." in token)


def _simulator_names(names: str | None, *, count: int) -> list[str]:
    raw = [name.strip() for name in names.split(",") if name.strip()] if names else []
    if not raw:
        raw = list(DEFAULT_SIMULATOR_NAMES)
    while len(raw) < count:
        raw.append(f"sim-{len(raw) + 1}")
    return raw[:count]
