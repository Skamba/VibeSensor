"""Run aggregate lifecycle and the run-status transition function."""

from __future__ import annotations

import pytest

from vibesensor.domain.run import Run
from vibesensor.domain.run_status import RunStatus, transition_run


class TestRun:
    def test_start_stop_lifecycle(self) -> None:
        run = Run()
        assert not run.is_recording

        run.start()
        assert run.is_recording

        run.stop()
        assert not run.is_recording

    def test_run_ids_are_unique(self) -> None:
        assert Run().run_id != Run().run_id

    def test_start_when_already_running_raises(self) -> None:
        run = Run()
        run.start()
        with pytest.raises(RuntimeError, match="Cannot start run"):
            run.start()

    def test_stop_before_start_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Cannot stop run"):
            Run().stop()

    def test_stopped_run_cannot_stop_or_restart(self) -> None:
        run = Run()
        run.start()
        run.stop()
        with pytest.raises(RuntimeError, match="Cannot stop run: already stopped"):
            run.stop()
        with pytest.raises(RuntimeError, match="Cannot start run: already started"):
            run.start()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.RECORDING, RunStatus.ANALYZING),
        (RunStatus.RECORDING, RunStatus.COMPLETE),
        (RunStatus.RECORDING, RunStatus.ERROR),
        (RunStatus.ANALYZING, RunStatus.COMPLETE),
        (RunStatus.ANALYZING, RunStatus.ERROR),
        (None, RunStatus.RECORDING),
        ("recording", "analyzing"),
    ],
)
def test_valid_run_transitions(current: RunStatus | str | None, target: RunStatus | str) -> None:
    assert transition_run(current, target) is RunStatus(target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.COMPLETE, RunStatus.RECORDING),
        (RunStatus.ERROR, RunStatus.RECORDING),
        (None, RunStatus.ANALYZING),
    ],
)
def test_invalid_run_transitions_raise(current: RunStatus | None, target: RunStatus) -> None:
    with pytest.raises(ValueError, match="Invalid run transition"):
        transition_run(current, target)
