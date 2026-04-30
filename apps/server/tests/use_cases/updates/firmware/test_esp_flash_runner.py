from __future__ import annotations

import asyncio

import pytest

from vibesensor.use_cases.updates.firmware.esp_flash_runner import (
    FLASH_CANCELLED_RETURN_CODE,
    FLASH_TIMEOUT_RETURN_CODE,
    SubprocessFlashCommandRunner,
)


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _BlockingStdout:
    async def readline(self) -> bytes:
        await asyncio.sleep(60)
        return b""


class _FakeFlashProcess:
    def __init__(
        self,
        lines: list[bytes] | None = None,
        *,
        ignore_terminate: bool = False,
    ) -> None:
        self.stdout = _FakeStdout(lines or [])
        self.returncode: int | None = None
        self.ignore_terminate = ignore_terminate
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        await asyncio.sleep(0)
        if self.returncode is None:
            if self.ignore_terminate and not self.killed:
                await asyncio.sleep(60)
            self.returncode = 0
        return self.returncode


@pytest.mark.asyncio
async def test_subprocess_flash_runner_returns_cancel_code_before_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeFlashProcess([])

    async def _fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return process

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.firmware.esp_flash_runner.asyncio.create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    cancel_event = asyncio.Event()
    cancel_event.set()
    lines: list[str] = []

    result = await SubprocessFlashCommandRunner().run(
        ["esptool.py", "erase_flash"],
        cwd="/tmp",
        line_cb=lines.append,
        cancel_event=cancel_event,
    )

    assert result == FLASH_CANCELLED_RETURN_CODE
    assert lines == ["Flash cancelled by request"]
    assert process.terminated is True
    assert process.killed is False


@pytest.mark.asyncio
async def test_subprocess_flash_runner_returns_cancel_code_during_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeFlashProcess([b"Connecting...\n"])

    async def _fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return process

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.firmware.esp_flash_runner.asyncio.create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    cancel_event = asyncio.Event()
    lines: list[str] = []

    def _line_cb(line: str) -> None:
        lines.append(line)
        if line == "Connecting...":
            cancel_event.set()

    result = await SubprocessFlashCommandRunner().run(
        ["esptool.py", "write_flash"],
        cwd="/tmp",
        line_cb=_line_cb,
        cancel_event=cancel_event,
    )

    assert result == FLASH_CANCELLED_RETURN_CODE
    assert lines == ["Connecting...", "Flash cancelled by request"]
    assert process.terminated is True
    assert process.killed is False


@pytest.mark.asyncio
async def test_subprocess_flash_runner_kills_timed_out_process_that_ignores_terminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeFlashProcess(ignore_terminate=True)
    process.stdout = _BlockingStdout()

    async def _fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return process

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.firmware.esp_flash_runner.FLASH_SHUTDOWN_WAIT_S",
        0.01,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.updates.firmware.esp_flash_runner.asyncio.create_subprocess_exec",
        _fake_create_subprocess_exec,
    )
    lines: list[str] = []

    result = await SubprocessFlashCommandRunner().run(
        ["esptool.py", "write_flash"],
        cwd="/tmp",
        line_cb=lines.append,
        cancel_event=asyncio.Event(),
        timeout_s=0.01,
    )

    assert result == FLASH_TIMEOUT_RETURN_CODE
    assert lines == ["Command timed out after 0s"]
    assert process.terminated is True
    assert process.killed is True
