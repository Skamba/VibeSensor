"""Core updater runtime assembly for status tracking and command execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.runner import (
    CommandRunner,
    UpdateCommandExecutor,
    UpdateStatusCommandReporter,
)
from vibesensor.use_cases.updates.status import (
    UpdateStateStore,
    UpdateStatusTracker,
    UpdateTerminalStateReporter,
    build_update_status_tracker,
    collect_runtime_details,
)

__all__ = ["UpdateRuntimeCore", "build_update_runtime_core"]


@dataclass(frozen=True, slots=True)
class UpdateRuntimeCore:
    status: UpdateStatusTracker
    reporter: UpdateTerminalStateReporter
    commands: UpdateCommandExecutor
    current_version_provider: Callable[[], str]


def build_update_runtime_core(
    *,
    runner: CommandRunner,
    repo: Path,
    state_store: UpdateStateStore,
) -> UpdateRuntimeCore:
    status = _build_status_tracker(
        repo=repo,
        state_store=state_store,
    )
    commands = UpdateCommandExecutor(
        runner=runner,
        reporter=UpdateStatusCommandReporter(status=status),
    )
    return UpdateRuntimeCore(
        status=status,
        reporter=UpdateTerminalStateReporter(status=status),
        commands=commands,
        current_version_provider=current_server_version,
    )


def _build_status_tracker(
    *,
    repo: Path,
    state_store: UpdateStateStore,
) -> UpdateStatusTracker:
    loaded = state_store.load()
    status = build_update_status_tracker(
        state_store=state_store,
        status=loaded,
    )
    status.set_runtime(collect_runtime_details(repo))
    return status


def current_server_version() -> str:
    from vibesensor import __version__ as current_version

    return current_version
