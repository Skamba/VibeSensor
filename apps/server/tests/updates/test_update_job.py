"""Behavioural tests for the linear ``UpdateJob`` flow with fake collaborators."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.common.exceptions import (
    UpdateCleanupError,
    UpdatePreparationError,
    UpdateReleaseError,
    UpdateTransportError,
)
from vibesensor.updates.firmware.firmware_refresh import FirmwareRefreshResult
from vibesensor.updates.job import UpdateJob
from vibesensor.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateState,
    UpdateTerminalState,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.updates.runner import CommandExecutionResult
from vibesensor.updates.status.payload_codec import UpdateStateStore
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.venv_slots import RevertedBoot

CURRENT_VERSION = "2026.4.3"


def _request() -> UpdateRequest:
    return UpdateRequest(
        transport=UpdateTransport.wifi,
        ssid="TestNet",
        password="pass123",
    )


def _running_tracker(tmp_path: Path, *phases: UpdatePhase) -> UpdateStatusTracker:
    tracker = build_update_status_harness(tmp_path / "state.json")
    tracker.start_job(_request())
    for phase in phases:
        tracker.transition(phase)
    return tracker


@dataclass(slots=True)
class _PreparedTransport:
    completed: bool = False

    async def complete_success(self) -> None:
        self.completed = True


@dataclass(slots=True)
class _Transport:
    """Fake transport coordinator: prepare/cleanup/recover with recorded calls."""

    status: UpdateStatusTracker | None = None
    prepared: _PreparedTransport = field(default_factory=_PreparedTransport)
    prepare_error: UpdateTransportError | None = None
    cleanup_error: UpdateCleanupError | None = None
    requests: list[UpdateRequest] = field(default_factory=list)
    cleaned: list[object | None] = field(default_factory=list)
    recovered: list[UpdateJobStatus] = field(default_factory=list)

    async def prepare(self, request: UpdateRequest) -> _PreparedTransport:
        self.requests.append(request)
        if self.prepare_error is not None:
            raise self.prepare_error
        if self.status is not None:
            self.status.transition(UpdatePhase.connecting_usb_internet)
        return self.prepared

    async def cleanup_after_update(self, prepared_transport: object | None) -> None:
        self.cleaned.append(prepared_transport)
        if self.cleanup_error is not None:
            raise self.cleanup_error

    async def recover_interrupted(self, status: UpdateJobStatus) -> None:
        self.recovered.append(status)


class _Fetcher:
    def __init__(self, release: object | None = None, error: Exception | None = None) -> None:
        self.release = release
        self.error = error

    def find_latest_release(self) -> object:
        if self.error is not None:
            raise self.error
        return self.release


class _Stager:
    def __init__(self, status: UpdateStatusTracker | None, wheel_path: Path) -> None:
        self._status = status
        self._wheel_path = wheel_path
        self.staged: list[object] = []

    @asynccontextmanager
    async def stage(self, release: object):
        if self._status is not None:
            self._status.transition(UpdatePhase.downloading)
        staged = SimpleNamespace(
            release=release,
            wheel_path=self._wheel_path,
            wheelhouse_dir=self._wheel_path.parent / "wheelhouse",
        )
        self.staged.append(staged)
        yield staged


class _FirmwareRefresher:
    def __init__(self, result: FirmwareRefreshResult | None = None) -> None:
        self.result = result or FirmwareRefreshResult.success()
        self.pinned_tags: list[str] = []

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> FirmwareRefreshResult:
        self.pinned_tags.append(pinned_tag)
        return self.result


class _Installer:
    """Fake slot installer: records the install request and the activation order."""

    def __init__(self, transport: _Transport, error: UpdateReleaseError | None = None) -> None:
        self._transport = transport
        self.error = error
        self.install_args: tuple[Path, Path, str] | None = None
        self.activated: list[tuple[str, bool]] = []

    async def install(self, wheel_path: Path, wheelhouse_dir: Path, version: str) -> str:
        self.install_args = (wheel_path, wheelhouse_dir, version)
        if self.error is not None:
            raise self.error
        return version

    def activate(self, slot: str) -> None:
        self.activated.append((slot, self._transport.prepared.completed))


class _Slots:
    def __init__(self, reverted: RevertedBoot | None = None) -> None:
        self.reverted = reverted

    def take_reverted(self) -> RevertedBoot | None:
        reverted, self.reverted = self.reverted, None
        return reverted


def _ok_commands() -> MagicMock:
    commands = MagicMock()
    commands.run = AsyncMock(
        return_value=CommandExecutionResult(returncode=0, stdout="", stderr=""),
    )
    return commands


@dataclass(slots=True)
class _Harness:
    job: UpdateJob
    status: UpdateStatusTracker
    transport: _Transport
    fetcher: _Fetcher
    stager: _Stager
    firmware: _FirmwareRefresher
    installer: _Installer
    commands: MagicMock


def _harness(
    tmp_path: Path,
    *,
    status: UpdateStatusTracker | None = None,
    latest_release: object | None = None,
    fetch_error: Exception | None = None,
    firmware_result: FirmwareRefreshResult | None = None,
    install_error: UpdateReleaseError | None = None,
    reverted: RevertedBoot | None = None,
    commands: MagicMock | None = None,
) -> _Harness:
    tracker = status or _running_tracker(tmp_path)
    transport = _Transport(status=tracker)
    fetcher = _Fetcher(
        latest_release
        if latest_release is not None
        else SimpleNamespace(tag=f"server-v{CURRENT_VERSION}", version=CURRENT_VERSION),
        error=fetch_error,
    )
    stager = _Stager(tracker, tmp_path / "release.whl")
    firmware = _FirmwareRefresher(firmware_result)
    installer = _Installer(transport, install_error)
    active_commands = commands or _ok_commands()
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    job = UpdateJob(
        status=tracker,
        commands=active_commands,
        transport=transport,
        release_fetcher=fetcher,
        stager=stager,
        firmware_refresher=firmware,
        installer=installer,
        slots=_Slots(reverted),
        validation_config=UpdateValidationConfig(
            venv_root=tmp_path / "venv",
            min_free_disk_bytes=1,
        ),
        repo=repo,
    )
    return _Harness(
        job=job,
        status=tracker,
        transport=transport,
        fetcher=fetcher,
        stager=stager,
        firmware=firmware,
        installer=installer,
        commands=active_commands,
    )


@pytest.fixture(autouse=True)
def _job_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vibesensor.__version__", CURRENT_VERSION)
    monkeypatch.setattr(
        "vibesensor.updates.job.validate_prerequisites",
        AsyncMock(return_value=None),
    )


# -- preparation -------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stops_before_transport_after_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)
    monkeypatch.setattr(
        "vibesensor.updates.job.validate_prerequisites",
        AsyncMock(side_effect=UpdatePreparationError("validation failed")),
    )

    with pytest.raises(UpdatePreparationError, match="validation failed"):
        await harness.job.run(_request())

    assert harness.transport.requests == []
    assert harness.transport.cleaned == [None]
    assert harness.firmware.pinned_tags == []


@pytest.mark.asyncio
async def test_run_stops_before_release_check_when_transport_cannot_prepare(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    harness.transport.prepare_error = UpdateTransportError("transport failed")
    request = _request()

    with pytest.raises(UpdateTransportError, match="transport failed"):
        await harness.job.run(request)

    assert harness.transport.requests == [request]
    assert harness.transport.cleaned == [None]
    assert harness.status.status.phase is UpdatePhase.validating
    assert harness.firmware.pinned_tags == []


# -- release check -----------------------------------------------------------


@pytest.mark.asyncio
async def test_run_refreshes_firmware_only_when_no_server_update_is_needed(
    tmp_path: Path,
) -> None:
    harness = _harness(
        tmp_path,
        latest_release=SimpleNamespace(tag="server-v2026.4.3", version=CURRENT_VERSION),
    )

    await harness.job.run(_request())

    assert harness.firmware.pinned_tags == ["server-v2026.4.3"]
    assert harness.stager.staged == []
    assert harness.transport.prepared.completed is True
    assert harness.transport.cleaned == [harness.transport.prepared]
    assert harness.status.status.state is UpdateState.success
    assert "Checking for available updates..." in harness.status.status.log_tail
    assert "Already up-to-date (version=2026.4.3)" in harness.status.status.log_tail
    assert "No server update needed; ESP firmware checked" in harness.status.status.log_tail


@pytest.mark.asyncio
async def test_run_fails_refresh_only_update_and_still_cleans_up_when_firmware_fails(
    tmp_path: Path,
) -> None:
    harness = _harness(
        tmp_path,
        firmware_result=FirmwareRefreshResult.failure(
            message="ESP firmware cache refresh failed (exit 1)",
            detail="cache unavailable",
        ),
    )

    with pytest.raises(UpdateReleaseError, match="ESP firmware cache refresh failed") as excinfo:
        await harness.job.run(_request())

    assert excinfo.value.phase == UpdatePhase.downloading.value
    assert excinfo.value.detail == "cache unavailable"
    assert (
        excinfo.value.log_message
        == "ESP firmware refresh failed; refresh-only update did not complete"
    )
    assert harness.transport.prepared.completed is False
    assert harness.transport.cleaned == [harness.transport.prepared]
    assert harness.status.status.state is UpdateState.running


@pytest.mark.asyncio
async def test_run_installs_release_when_latest_version_is_newer(tmp_path: Path) -> None:
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")
    harness = _harness(tmp_path, latest_release=release)

    await harness.job.run(_request())

    assert [staged.release for staged in harness.stager.staged] == [release]
    assert harness.firmware.pinned_tags == ["server-v2026.4.4"]
    assert harness.installer.install_args == (
        tmp_path / "release.whl",
        tmp_path / "wheelhouse",
        "2026.4.4",
    )
    # The new slot only becomes active after the transport finished successfully.
    assert harness.installer.activated == [("2026.4.4", True)]
    assert harness.status.status.state is UpdateState.success
    assert harness.status.status.issues == []
    assert "Update available: 2026.4.3 → 2026.4.4" in harness.status.status.log_tail
    assert "Update to 2026.4.4 installed; restarting into it" in harness.status.status.log_tail
    assert harness.commands.run.await_args.args[0][0] == "systemd-run"


@pytest.mark.asyncio
async def test_run_keeps_the_live_slot_when_install_fails(tmp_path: Path) -> None:
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")
    harness = _harness(
        tmp_path,
        latest_release=release,
        install_error=UpdateReleaseError("Version 2026.4.4 failed its smoke test (exit 1)"),
    )

    with pytest.raises(UpdateReleaseError, match="failed its smoke test"):
        await harness.job.run(_request())

    assert harness.status.status.phase is UpdatePhase.installing
    assert harness.installer.activated == []
    assert harness.transport.prepared.completed is False
    harness.commands.run.assert_not_awaited()
    assert harness.transport.cleaned == [harness.transport.prepared]


@pytest.mark.asyncio
async def test_run_records_firmware_refresh_failure_and_still_installs(tmp_path: Path) -> None:
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")
    harness = _harness(
        tmp_path,
        latest_release=release,
        firmware_result=FirmwareRefreshResult.failure(
            message="ESP firmware cache refresh failed (exit 4)",
            detail="download timed out",
        ),
    )

    await harness.job.run(_request())

    assert harness.installer.install_args == (
        tmp_path / "release.whl",
        tmp_path / "wheelhouse",
        "2026.4.4",
    )
    assert harness.status.status.issues[-1].message == "ESP firmware cache refresh failed (exit 4)"
    assert harness.status.status.issues[-1].detail == "download timed out"
    assert (
        "ESP firmware refresh failed; continuing with existing cache"
        in harness.status.status.log_tail
    )
    assert harness.transport.prepared.completed is True
    assert harness.status.status.state is UpdateState.success


@pytest.mark.asyncio
async def test_run_treats_older_latest_release_as_up_to_date(tmp_path: Path) -> None:
    harness = _harness(
        tmp_path,
        latest_release=SimpleNamespace(tag="server-v2026.4.2", version="2026.4.2"),
    )

    await harness.job.run(_request())

    assert harness.stager.staged == []
    assert harness.firmware.pinned_tags == ["server-v2026.4.2"]


@pytest.mark.asyncio
async def test_run_raises_release_error_when_release_check_fails(tmp_path: Path) -> None:
    harness = _harness(tmp_path, fetch_error=OSError("rate limited"))

    with pytest.raises(UpdateReleaseError, match="rate limited") as excinfo:
        await harness.job.run(_request())

    assert excinfo.value.phase == "checking"
    assert str(excinfo.value) == "Failed to check for updates: rate limited"
    assert harness.status.status.phase is UpdatePhase.checking
    assert harness.transport.cleaned == [harness.transport.prepared]


# -- success completion and restart scheduling ------------------------------


@pytest.mark.asyncio
async def test_completion_marks_success_then_schedules_restart(tmp_path: Path) -> None:
    status = UpdateStatusTracker(
        state_store=UpdateStateStore(tmp_path / "update_status.json"),
        status=UpdateJobStatus(state=UpdateState.running, phase=UpdatePhase.installing),
    )
    harness = _harness(tmp_path, status=status)

    await harness.job._finish_success("Update completed successfully")

    harness.commands.run.assert_awaited_once()
    assert status.status.state is UpdateState.success
    assert status.status.terminal_state is UpdateTerminalState.success
    assert status.status.log_tail == [
        "Update completed successfully",
        "Scheduled backend service restart",
    ]
    assert status.status.issues == []


@pytest.mark.asyncio
async def test_completion_records_issue_when_restart_scheduling_fails(tmp_path: Path) -> None:
    status = UpdateStatusTracker(
        state_store=UpdateStateStore(tmp_path / "update_status.json"),
        status=UpdateJobStatus(state=UpdateState.running, phase=UpdatePhase.checking),
    )
    commands = MagicMock()
    commands.run = AsyncMock(
        return_value=CommandExecutionResult(returncode=1, stdout="", stderr="boom"),
    )
    harness = _harness(tmp_path, status=status, commands=commands)

    await harness.job._finish_success("No server update needed; ESP firmware checked")

    assert commands.run.await_count == 2
    assert status.status.state is UpdateState.success
    assert status.status.log_tail == [
        "No server update needed; ESP firmware checked",
        "Automatic backend restart scheduling failed",
    ]
    assert [(issue.phase, issue.message, issue.detail) for issue in status.status.issues] == [
        (
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        ),
    ]


_SYSTEMD_RUN_RESTART = [
    "systemd-run",
    "--unit",
    "vibesensor-post-update-restart",
    "--on-active=2s",
    "systemctl",
    "restart",
    "vibesensor.service",
]


@pytest.mark.asyncio
async def test_schedule_restart_uses_systemd_run_when_available(tmp_path: Path) -> None:
    harness = _harness(tmp_path)

    assert await harness.job._schedule_restart() is True
    harness.commands.run.assert_awaited_once()
    assert harness.commands.run.await_args.args[0] == _SYSTEMD_RUN_RESTART
    assert harness.commands.run.await_args.kwargs == {
        "phase": "done",
        "timeout": 30,
        "sudo": True,
    }


@pytest.mark.asyncio
async def test_schedule_restart_falls_back_to_direct_systemctl_restart(tmp_path: Path) -> None:
    commands = MagicMock()
    commands.run = AsyncMock(
        side_effect=[
            CommandExecutionResult(returncode=1, stdout="", stderr="boom"),
            CommandExecutionResult(returncode=0, stdout="", stderr=""),
        ],
    )
    harness = _harness(tmp_path, commands=commands)

    assert await harness.job._schedule_restart() is True
    assert [call.args[0] for call in commands.run.await_args_list] == [
        _SYSTEMD_RUN_RESTART,
        ["systemctl", "restart", "vibesensor.service"],
    ]


# -- finalization -------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_cleans_up_transport_then_refreshes_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)
    refresh = AsyncMock()
    monkeypatch.setattr(UpdateJob, "_refresh_runtime_details", refresh)
    prepared_transport = object()

    await harness.job._finalize(prepared_transport)

    assert harness.transport.cleaned == [prepared_transport]
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_adds_cleanup_note_to_prior_failure(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.transport.cleanup_error = UpdateCleanupError("transport cleanup failed")
    runtime_before = harness.status.status.runtime
    workflow_error = RuntimeError("workflow bug")

    await harness.job._finalize(object(), prior_error=workflow_error)

    assert workflow_error.__notes__ == ["Cleanup also failed: transport cleanup failed"]
    assert harness.status.status.runtime is runtime_before


@pytest.mark.asyncio
async def test_finalize_raises_cleanup_error_when_cleanup_fails_after_cancellation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    harness.transport.cleanup_error = UpdateCleanupError("transport cleanup failed")

    with pytest.raises(
        UpdateCleanupError,
        match="Cleanup failed after cancellation: transport cleanup failed",
    ):
        await harness.job._finalize(object(), prior_error=asyncio.CancelledError())


@pytest.mark.asyncio
async def test_finalize_raises_cleanup_error_without_prior_failure(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.transport.cleanup_error = UpdateCleanupError("transport cleanup failed")

    with pytest.raises(UpdateCleanupError, match="^transport cleanup failed$"):
        await harness.job._finalize(object())


# -- startup recovery ----------------------------------------------------------


def _recovery_harness(
    tmp_path: Path,
    status: UpdateJobStatus,
    *,
    reverted: RevertedBoot | None = None,
) -> _Harness:
    tracker = UpdateStatusTracker(
        state_store=UpdateStateStore(tmp_path / "update_status.json"),
        status=status,
    )
    return _harness(tmp_path, status=tracker, reverted=reverted)


@pytest.mark.asyncio
async def test_recover_skips_non_running_jobs(tmp_path: Path) -> None:
    status = UpdateJobStatus(state=UpdateState.idle)
    harness = _recovery_harness(tmp_path, status)

    await harness.job.recover_interrupted()

    assert harness.transport.recovered == []
    assert status.state is UpdateState.idle
    assert status.issues == []


@pytest.mark.asyncio
async def test_recover_marks_interrupted_and_recovers_transport(
    tmp_path: Path,
) -> None:
    status = UpdateJobStatus(
        state=UpdateState.running,
        phase=UpdatePhase.installing,
        transport=UpdateTransport.usb_internet,
    )
    harness = _recovery_harness(tmp_path, status)

    await harness.job.recover_interrupted()

    assert harness.transport.recovered == [status]
    assert status.state is UpdateState.failed
    assert [(issue.phase, issue.message) for issue in status.issues] == [
        ("startup", "Update interrupted by server restart"),
    ]


@pytest.mark.asyncio
async def test_recover_reports_a_boot_check_revert_as_a_failed_update(tmp_path: Path) -> None:
    status = UpdateJobStatus(
        state=UpdateState.success,
        phase=UpdatePhase.done,
        finished_at=100.0,
        terminal_state=UpdateTerminalState.success,
    )
    harness = _recovery_harness(
        tmp_path,
        status,
        reverted=RevertedBoot(
            candidate="2026.4.4",
            previous="2026.4.3",
            reason="not healthy within 60 s of starting",
        ),
    )

    await harness.job.recover_interrupted()

    current = harness.status.status
    assert current.state is UpdateState.failed
    assert current.terminal_state is UpdateTerminalState.workflow_failed
    assert [(issue.phase, issue.message, issue.detail) for issue in current.issues] == [
        (
            "installing",
            "Version 2026.4.4 did not start healthy; reverted to 2026.4.3",
            "not healthy within 60 s of starting",
        ),
    ]
    assert harness.transport.recovered == []
    persisted = UpdateStateStore(tmp_path / "update_status.json").load()
    assert persisted.state is UpdateState.failed


@pytest.mark.asyncio
async def test_recover_repairs_cleanup_failed_terminal_state(tmp_path: Path) -> None:
    status = UpdateJobStatus(
        state=UpdateState.failed,
        finished_at=123.0,
        terminal_state=UpdateTerminalState.timeout_cleanup_failed,
    )
    harness = _recovery_harness(tmp_path, status)

    await harness.job.recover_interrupted()

    assert harness.transport.recovered == [status]
    assert status.state is UpdateState.failed
    assert status.issues == []
