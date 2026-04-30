from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.runner import (
    CommandExecutionResult,
    CommandRunner,
    UpdateCommandExecutor,
    UpdateStatusCommandReporter,
)


class _StaticRunner(CommandRunner):
    def __init__(self, *, response: CommandExecutionResult) -> None:
        self.calls: list[tuple[list[str], float, dict[str, str] | None]] = []
        self._response = response

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        self.calls.append((list(args), timeout, env))
        return (self._response.returncode, self._response.stdout, self._response.stderr)


class _CancellableProcess:
    def __init__(self, *, block_wait: bool = False) -> None:
        self.returncode: int | None = None
        self.block_wait = block_wait
        self.communicate_started = asyncio.Event()
        self.wait_called = asyncio.Event()
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        self.communicate_started.set()
        await asyncio.sleep(60)
        return (b"", b"")

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_called.set()
        if self.block_wait:
            await asyncio.sleep(60)
        await asyncio.sleep(0)
        return self.returncode if self.returncode is not None else 0


@pytest.mark.asyncio
async def test_update_command_executor_returns_structured_result_without_reporter() -> None:
    runner = _StaticRunner(response=CommandExecutionResult(returncode=0, stdout="ok\n", stderr=""))
    executor = UpdateCommandExecutor(runner=runner)

    result = await executor.run(["echo", "ok"], phase="checking", timeout=5)

    assert result == CommandExecutionResult(returncode=0, stdout="ok\n", stderr="")
    assert runner.calls == [(["echo", "ok"], 5, None)]


@pytest.mark.asyncio
async def test_status_command_reporter_logs_redacted_command_output_and_exit_code(
    tmp_path: Path,
) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    runner = _StaticRunner(
        response=CommandExecutionResult(
            returncode=7,
            stdout="stdout line\n",
            stderr="psk=mysecretpassword\n",
        ),
    )
    executor = UpdateCommandExecutor(
        runner=runner,
        reporter=UpdateStatusCommandReporter(status=status),
    )

    result = await executor.run(
        [
            "nmcli",
            "connection",
            "modify",
            "VibeSensor-Uplink",
            "wifi-sec.psk",
            "supersecret",
        ],
        phase="connecting_wifi",
        timeout=5,
    )

    assert result.returncode == 7
    assert any(
        line.endswith(
            "[connecting_wifi] $ nmcli connection modify VibeSensor-Uplink wifi-sec.psk ***",
        )
        for line in status.status.log_tail
    )
    assert any("[connecting_wifi] stdout: stdout line" in line for line in status.status.log_tail)
    assert any("[connecting_wifi] stderr: psk=***" in line for line in status.status.log_tail)
    assert any("[connecting_wifi] exit code: 7" in line for line in status.status.log_tail)


@pytest.mark.asyncio
async def test_command_runner_waits_for_killed_process_on_task_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _CancellableProcess()

    async def _fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return process

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.runner.asyncio.create_subprocess_exec",
        _fake_create_subprocess_exec,
    )

    task = asyncio.create_task(CommandRunner().run(["sleep", "60"], timeout=30))
    await asyncio.wait_for(process.communicate_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    assert process.killed is True
    assert process.wait_called.is_set()


@pytest.mark.asyncio
async def test_command_runner_bounds_wait_after_timeout_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _CancellableProcess(block_wait=True)

    async def _fake_create_subprocess_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return process

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.runner.COMMAND_KILL_WAIT_S",
        0.01,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.updates.runner.asyncio.create_subprocess_exec",
        _fake_create_subprocess_exec,
    )

    result = await CommandRunner().run(["sleep", "60"], timeout=0.01)

    assert result == (124, "", "Command timed out")
    assert process.killed is True
    assert process.wait_called.is_set()
