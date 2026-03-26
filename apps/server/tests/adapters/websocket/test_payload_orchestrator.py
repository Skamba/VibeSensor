"""PayloadBuildOrchestrator coverage for caching and serialization fallbacks."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

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
