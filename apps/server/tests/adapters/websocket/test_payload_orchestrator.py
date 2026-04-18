"""PayloadBuildOrchestrator coverage for caching and serialization fallbacks."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import orjson
import pytest

from vibesensor.adapters.websocket.payload_orchestrator import PayloadBuildOrchestrator


@pytest.mark.asyncio
async def test_prepare_builds_payload_once_per_unique_selection() -> None:
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})
    orchestrator = PayloadBuildOrchestrator(payload_builder, capture_debug=False)

    await orchestrator.prepare(["same", "same", None])

    assert payload_builder.call_count == 2
    assert json.loads(orchestrator.payload_cache["same"]) == {"selected": "same"}
    assert json.loads(orchestrator.payload_cache[None]) == {"selected": None}


@pytest.mark.asyncio
async def test_get_or_build_payload_text_reuses_pending_task() -> None:
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})
    orchestrator = PayloadBuildOrchestrator(payload_builder, capture_debug=False)

    async def fake_to_thread(func, /, *args, **kwargs):
        await asyncio.sleep(0)
        return func(*args, **kwargs)

    with patch(
        "vibesensor.adapters.websocket.payload_orchestrator.asyncio.to_thread",
        side_effect=fake_to_thread,
    ):
        first, second = await asyncio.gather(
            orchestrator.get_or_build_payload_text("same"),
            orchestrator.get_or_build_payload_text("same"),
        )

    assert first == second
    assert payload_builder.call_count == 1


@pytest.mark.asyncio
async def test_prepare_falls_back_to_error_payload_on_serialization_failure() -> None:
    payload_builder = MagicMock(return_value={"bad": object()})
    orchestrator = PayloadBuildOrchestrator(payload_builder, capture_debug=False)

    with patch(
        "vibesensor.adapters.websocket.payload_orchestrator.sanitize_for_json",
        return_value=({"still_bad": object()}, False),
    ):
        await orchestrator.prepare(["broken"])

    assert orchestrator.failed_client_ids == {"broken"}
    assert json.loads(orchestrator.payload_cache["broken"]) == {
        "error": "payload_build_failed",
    }


@pytest.mark.asyncio
async def test_prepare_reuses_serialized_template_across_selected_clients() -> None:
    shared_clients = [{"id": "sensor-a", "connected": True}]
    shared_rotational_speeds = {
        "basis_speed_source": None,
        "wheel": {"rpm": None, "mode": None, "reason": None},
        "driveshaft": {"rpm": None, "mode": None, "reason": None},
        "engine": {"rpm": None, "mode": None, "reason": None},
        "order_bands": None,
    }

    def payload_builder(selected: str | None) -> dict[str, object]:
        return {
            "schema_version": "1",
            "server_time": "2026-04-18T00:00:00Z",
            "speed_mps": None,
            "clients": shared_clients,
            "selected_client_id": selected,
            "rotational_speeds": shared_rotational_speeds,
        }

    orchestrator = PayloadBuildOrchestrator(payload_builder, capture_debug=False)
    dict_dump_calls = 0
    real_dumps = orjson.dumps

    def counting_dumps(value: object) -> str:
        nonlocal dict_dump_calls
        if isinstance(value, dict):
            dict_dump_calls += 1
        return real_dumps(value).decode()

    with patch(
        "vibesensor.adapters.websocket.payload_orchestrator._dump_json_text",
        side_effect=counting_dumps,
    ):
        await orchestrator.prepare(["sensor-a", "sensor-b"])

    assert dict_dump_calls == 1
    assert json.loads(orchestrator.payload_cache["sensor-a"])["selected_client_id"] == "sensor-a"
    assert json.loads(orchestrator.payload_cache["sensor-b"])["selected_client_id"] == "sensor-b"
