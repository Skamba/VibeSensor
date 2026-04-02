from __future__ import annotations

import asyncio

import pytest

from vibesensor.adapters.simulator.sim_runtime import command_loop


@pytest.mark.asyncio
async def test_command_loop_handles_value_error_and_continues(monkeypatch, capsys) -> None:
    stop_event = asyncio.Event()
    prompts = iter(["bad", "quit"])
    calls: list[str] = []

    async def fake_to_thread(_func, _prompt: str) -> str:
        return next(prompts)

    def fake_apply_command(_clients, line: str, stop: asyncio.Event, _profiles):
        calls.append(line)
        if line == "bad":
            raise ValueError("bad value")
        stop.set()
        return "Stopping simulator..."

    monkeypatch.setattr(
        "vibesensor.adapters.simulator.sim_runtime.asyncio.to_thread",
        fake_to_thread,
    )
    monkeypatch.setattr(
        "vibesensor.adapters.simulator.sim_runtime.apply_command",
        fake_apply_command,
    )

    await command_loop([], stop_event)

    assert calls == ["bad", "quit"]
    assert "Command error: bad value" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_command_loop_propagates_unexpected_command_errors(monkeypatch) -> None:
    stop_event = asyncio.Event()

    async def fake_to_thread(_func, _prompt: str) -> str:
        return "boom"

    def fake_apply_command(_clients, _line: str, _stop: asyncio.Event, _profiles):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "vibesensor.adapters.simulator.sim_runtime.asyncio.to_thread",
        fake_to_thread,
    )
    monkeypatch.setattr(
        "vibesensor.adapters.simulator.sim_runtime.apply_command",
        fake_apply_command,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await command_loop([], stop_event)
