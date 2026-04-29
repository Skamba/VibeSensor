from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from vibesensor.adapters.simulator.sim_runtime import command_loop


@dataclass
class _SummaryFailingClient:
    name: str = "front-left"
    client_id: bytes = b"\x01\x02\x03\x04\x05\x06"
    profile_name: str = "engine_idle"
    scene_mode: str = "road"
    scene_gain: float = 1.0
    scene_noise_gain: float = 1.0
    amp_scale: float = 1.0
    noise_scale: float = 1.0
    common_event_gain: float = 0.0
    paused: bool = False

    @property
    def mac_address(self) -> str:
        return "01:02:03:04:05:06"

    def pulse(self, _strength: float) -> None:
        return None

    def summary(self) -> str:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_command_loop_handles_command_parse_error_and_continues(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stop_event = asyncio.Event()
    prompts = iter(['bad "quote', "quit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(prompts))

    await command_loop([], stop_event)

    output = capsys.readouterr().out
    assert stop_event.is_set()
    assert "Command error:" in output
    assert "Stopping simulator..." in output


@pytest.mark.asyncio
async def test_command_loop_propagates_unexpected_command_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    monkeypatch.setattr("builtins.input", lambda _prompt: "list")

    with pytest.raises(RuntimeError, match="boom"):
        await command_loop([_SummaryFailingClient()], stop_event)
