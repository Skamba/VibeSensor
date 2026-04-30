"""PayloadBuildOrchestrator coverage for caching and serialization fallbacks."""

from __future__ import annotations

import asyncio
import json
import time

import anyio
import pytest

from vibesensor.adapters.websocket.payload_orchestrator import PayloadBuildOrchestrator


class _PayloadBuilder:
    def __init__(self, *, delay_s: float = 0.0, payload_factory=None) -> None:
        self._delay_s = delay_s
        self._payload_factory = payload_factory or (lambda selected: {"selected": selected})

    def __call__(self, selected: str | None) -> dict[str, object]:
        if self._delay_s:
            time.sleep(self._delay_s)
        return self._payload_factory(selected)


@pytest.mark.asyncio
async def test_prepare_caches_payload_text_for_selected_clients() -> None:
    orchestrator = PayloadBuildOrchestrator(_PayloadBuilder(), capture_debug=False)

    await orchestrator.prepare(["same", "same", None])

    assert set(orchestrator.payload_cache) == {"same", None}
    assert json.loads(orchestrator.payload_cache["same"]) == {"selected": "same"}
    assert json.loads(orchestrator.payload_cache[None]) == {"selected": None}


@pytest.mark.asyncio
async def test_get_or_build_payload_text_returns_same_payload_for_concurrent_calls() -> None:
    orchestrator = PayloadBuildOrchestrator(
        _PayloadBuilder(delay_s=0.05),
        capture_debug=False,
    )
    first, second = await asyncio.gather(
        orchestrator.get_or_build_payload_text("same"),
        orchestrator.get_or_build_payload_text("same"),
    )

    assert first == second
    assert first == orchestrator.payload_cache["same"]
    assert json.loads(first) == {"selected": "same"}


@pytest.mark.asyncio
async def test_prepare_falls_back_to_error_payload_on_serialization_failure() -> None:
    orchestrator = PayloadBuildOrchestrator(
        _PayloadBuilder(payload_factory=lambda selected: {"selected": selected, "bad": object()}),
        capture_debug=False,
    )

    await orchestrator.prepare(["broken"])

    assert orchestrator.failed_client_ids == {"broken"}
    assert json.loads(orchestrator.payload_cache["broken"]) == {
        "error": "payload_build_failed",
    }


@pytest.mark.asyncio
async def test_prepare_replaces_non_finite_values_with_null() -> None:
    orchestrator = PayloadBuildOrchestrator(
        _PayloadBuilder(
            payload_factory=lambda selected: {
                "selected_client_id": selected,
                "value": float("nan"),
            }
        ),
        capture_debug=False,
    )

    await orchestrator.prepare(["sensor-a"])

    assert json.loads(orchestrator.payload_cache["sensor-a"]) == {
        "selected_client_id": "sensor-a",
        "value": None,
    }


@pytest.mark.asyncio
async def test_prepare_bounds_concurrent_serialization(monkeypatch: pytest.MonkeyPatch) -> None:
    active = 0
    max_active = 0

    async def _fake_run_sync(func, *args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await anyio.sleep(0.01)
        try:
            return func(*args)
        finally:
            active -= 1

    monkeypatch.setattr(
        "vibesensor.adapters.websocket.payload_orchestrator.anyio.to_thread.run_sync",
        _fake_run_sync,
    )
    orchestrator = PayloadBuildOrchestrator(
        _PayloadBuilder(),
        capture_debug=False,
        max_concurrent_serializations=2,
    )

    await orchestrator.prepare([f"sensor-{index}" for index in range(7)])

    assert max_active == 2
    assert orchestrator.serialized_payload_count == 7


@pytest.mark.asyncio
async def test_prepare_skips_payload_variants_over_budget() -> None:
    orchestrator = PayloadBuildOrchestrator(
        _PayloadBuilder(),
        capture_debug=False,
        max_payload_variants=2,
    )

    await orchestrator.prepare(["sensor-a", "sensor-b", "sensor-c"])

    assert set(orchestrator.payload_cache) == {"sensor-a", "sensor-b", "sensor-c"}
    assert orchestrator.skipped_client_ids == {"sensor-c"}
    assert json.loads(orchestrator.payload_cache["sensor-c"]) == {"error": "payload_build_failed"}
