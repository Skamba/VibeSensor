from __future__ import annotations

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
