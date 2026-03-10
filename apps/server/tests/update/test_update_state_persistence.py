"""Tests for update state persistence and interrupted-job recovery."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.update.manager import UpdateManager
from vibesensor.update.models import UpdateIssue, UpdateJobStatus, UpdatePhase, UpdateState
from vibesensor.update.runner import CommandRunner
from vibesensor.update.status import UpdateStateStore, UpdateStatusTracker

# ---------------------------------------------------------------------------
# Fake runner (minimal; only records calls)
# ---------------------------------------------------------------------------


class FakeRunner(CommandRunner):
    """Test double that returns rc=0 for everything."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.responses: list[tuple[str, tuple[int, str, str]]] = []
        self.default_response: tuple[int, str, str] = (0, "", "")

    def set_response(self, match_substr: str, rc: int, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((match_substr, (rc, stdout, stderr)))

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        self.calls.append((list(args), {"timeout": timeout, "env": env}))
        joined = " ".join(args)
        for match_substr, response in self.responses:
            if match_substr in joined:
                return response
        return self.default_response


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _mock_which(name: str) -> str | None:
    """Fake ``shutil.which`` recognising only ``nmcli`` and ``python3``."""
    return f"/usr/bin/{name}" if name in ("nmcli", "python3") else None


@pytest.fixture
def update_env(
    tmp_path: Path,
) -> tuple[Path, UpdateStateStore, FakeRunner, Callable[..., UpdateManager]]:
    """Provide ``(state_path, store, runner, make_mgr)`` for update-state tests.

    ``make_mgr(**overrides)`` creates an ``UpdateManager`` wired to *store* and
    *runner* (both reused across calls within the same test).
    """
    state_path = tmp_path / "state.json"
    store = UpdateStateStore(path=state_path)
    runner = FakeRunner()

    def _make_mgr(**kw: object) -> UpdateManager:
        return UpdateManager(
            runner=kw.pop("runner", runner),  # type: ignore[arg-type]
            repo_path=kw.pop("repo_path", str(tmp_path / "repo")),  # type: ignore[arg-type]
            rollback_dir=kw.pop("rollback_dir", str(tmp_path / "rollback")),  # type: ignore[arg-type]
            state_store=kw.pop("state_store", store),  # type: ignore[arg-type]
        )

    return state_path, store, runner, _make_mgr


# ---------------------------------------------------------------------------
# UpdateJobStatus round-trip (to_dict / from_dict)
# ---------------------------------------------------------------------------


class TestUpdateJobStatusRoundTrip:
    def test_idle_round_trip(self) -> None:
        status = UpdateJobStatus()
        restored = UpdateJobStatus.from_dict(status.to_dict())
        assert restored.state == UpdateState.idle
        assert restored.phase == UpdatePhase.idle
        assert restored.issues == []
        assert restored.log_tail == []
        assert restored.phase_started_at is None
        assert restored.updated_at is None

    def test_full_status_round_trip(self) -> None:
        status = UpdateJobStatus(
            state=UpdateState.failed,
            phase=UpdatePhase.installing,
            started_at=1700000000.0,
            finished_at=1700000120.0,
            last_success_at=1699999000.0,
            phase_started_at=1700000005.0,
            updated_at=1700000060.0,
            ssid="MyNetwork",
            issues=[
                UpdateIssue(phase="installing", message="Wheel failed", detail="rc=1"),
                UpdateIssue(phase="restoring_hotspot", message="No AP"),
            ],
            log_tail=["line1", "line2", "line3"],
            exit_code=1,
            runtime={"version": "1.0.0"},
        )
        restored = UpdateJobStatus.from_dict(status.to_dict())
        assert restored.state == UpdateState.failed
        assert restored.phase == UpdatePhase.installing
        assert restored.started_at == 1700000000.0
        assert restored.finished_at == 1700000120.0
        assert restored.last_success_at == 1699999000.0
        assert restored.phase_started_at == 1700000005.0
        assert restored.updated_at == 1700000060.0
        assert restored.ssid == "MyNetwork"
        assert len(restored.issues) == 2
        assert restored.issues[0].phase == "installing"
        assert restored.issues[0].message == "Wheel failed"
        assert restored.issues[0].detail == "rc=1"
        assert restored.issues[1].phase == "restoring_hotspot"
        assert restored.log_tail == ["line1", "line2", "line3"]
        assert restored.exit_code == 1
        assert restored.runtime == {"version": "1.0.0"}


# ---------------------------------------------------------------------------
# UpdateStateStore: save / load / corruption
# ---------------------------------------------------------------------------


class TestUpdateStateStore:
    def test_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        store = UpdateStateStore(path=path)

        status = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.downloading,
            started_at=1700000000.0,
            ssid="TestWifi",
            issues=[UpdateIssue(phase="validating", message="ok")],
            log_tail=["log entry 1"],
        )
        store.save(status)
        assert path.is_file()

        loaded = store.load()
        assert loaded is not None
        assert loaded.state == UpdateState.running
        assert loaded.phase == UpdatePhase.downloading
        assert loaded.ssid == "TestWifi"
        assert loaded.phase_started_at is None
        assert len(loaded.issues) == 1
        assert loaded.issues[0].message == "ok"
        assert loaded.log_tail == ["log entry 1"]

    @pytest.mark.parametrize(
        "file_content",
        [
            pytest.param(None, id="missing_file"),
            pytest.param("{this is not valid json}", id="corrupted_json"),
            pytest.param("", id="empty_file"),
        ],
    )
    def test_load_returns_none_for_bad_input(
        self,
        tmp_path: Path,
        file_content: str | None,
    ) -> None:
        path = tmp_path / "state.json"
        if file_content is not None:
            path.write_text(file_content, encoding="utf-8")
        store = UpdateStateStore(path=path)
        assert store.load() is None

    def test_load_normalizes_invalid_state_to_idle(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text('{"state": "bogus", "phase": "idle"}', encoding="utf-8")
        store = UpdateStateStore(path=path)

        loaded = store.load()

        assert loaded is not None
        assert loaded.state == UpdateState.idle
        assert loaded.phase == UpdatePhase.idle

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "state.json"
        store = UpdateStateStore(path=path)
        store.save(UpdateJobStatus())
        assert path.is_file()

    def test_atomic_write_leaves_no_temp_files(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        store = UpdateStateStore(path=path)
        store.save(UpdateJobStatus())
        # Only the final file should exist (no .tmp leftovers)
        assert list(tmp_path.iterdir()) == [path]


# ---------------------------------------------------------------------------
# No secrets in persisted file
# ---------------------------------------------------------------------------


class TestNoSecretsInPersistedFile:
    @pytest.mark.asyncio
    async def test_password_not_in_persisted_json(self, update_env) -> None:
        """Wi-Fi password must never appear in the persisted status file."""
        state_path, _, runner, make_mgr = update_env
        runner.set_response("sudo -n true", 0)
        mgr = make_mgr()

        secret_password = "SuperSecret!WiFi#Password42"

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", secret_password)
            assert mgr._task is not None
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(mgr._task, timeout=15)

        assert state_path.is_file(), "State file should have been created"
        contents = state_path.read_text(encoding="utf-8")
        assert secret_password not in contents, "Password leaked into persisted state file!"


# ---------------------------------------------------------------------------
# Startup recovery for interrupted jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStartupRecovery:
    async def test_interrupted_running_job_becomes_failed(self, update_env) -> None:
        """A persisted running job (no finished_at) is marked failed on startup."""
        state_path, store, _, make_mgr = update_env

        store.save(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.installing,
                started_at=time.time() - 60,
                ssid="CrashNet",
                log_tail=["some log"],
            ),
        )
        mgr = make_mgr()

        assert mgr.status.state == UpdateState.running
        await mgr.startup_recover()

        assert mgr.status.state == UpdateState.failed
        assert mgr.status.finished_at is not None
        issue_messages = [i.message for i in mgr.status.issues]
        assert any("interrupted" in m.lower() or "restart" in m.lower() for m in issue_messages)

        reloaded = store.load()
        assert reloaded is not None
        assert reloaded.state == UpdateState.failed
        assert reloaded.finished_at is not None

    async def test_idle_status_no_recovery_needed(self, update_env) -> None:
        """An idle persisted status should not trigger recovery."""
        _, store, _, make_mgr = update_env
        store.save(UpdateJobStatus())
        mgr = make_mgr()

        await mgr.startup_recover()
        assert mgr.status.state == UpdateState.idle
        assert mgr.status.finished_at is None

    async def test_finished_running_job_no_recovery(self, update_env) -> None:
        """A running job WITH finished_at set does not trigger recovery."""
        _, store, _, make_mgr = update_env
        store.save(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.done,
                started_at=time.time() - 60,
                finished_at=time.time() - 30,
            ),
        )
        mgr = make_mgr()

        await mgr.startup_recover()
        issue_messages = [i.message for i in mgr.status.issues]
        assert not any("interrupted" in m.lower() for m in issue_messages)

    async def test_recovery_attempts_network_cleanup(self, update_env) -> None:
        """Startup recovery attempts to clean up uplink and restore hotspot."""
        _, store, runner, make_mgr = update_env
        store.save(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.connecting_wifi,
                started_at=time.time() - 60,
            ),
        )
        mgr = make_mgr()

        await mgr.startup_recover()

        all_args = [" ".join(c[0]) for c in runner.calls]
        assert any("connection down" in a for a in all_args)
        assert any("connection delete" in a for a in all_args)
        assert any("connection up" in a for a in all_args)

    async def test_recovery_handles_nmcli_failure_gracefully(self, update_env) -> None:
        """If nmcli fails during recovery, it adds issues but doesn't crash."""
        _, store, runner, make_mgr = update_env
        store.save(
            UpdateJobStatus(
                state=UpdateState.running,
                phase=UpdatePhase.downloading,
                started_at=time.time() - 60,
            ),
        )
        runner.default_response = (1, "", "nmcli not found")
        mgr = make_mgr()

        with (
            patch("vibesensor.update.network.HOTSPOT_RESTORE_RETRIES", 1),
            patch("vibesensor.update.network.HOTSPOT_RESTORE_DELAY_S", 0),
        ):
            await mgr.startup_recover()

        assert mgr.status.state == UpdateState.failed
        assert mgr.status.finished_at is not None


# ---------------------------------------------------------------------------
# Persistence during update lifecycle
# ---------------------------------------------------------------------------


class TestPersistenceDuringLifecycle:
    def test_phase_transition_updates_phase_started_and_updated_at(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        tracker = UpdateStatusTracker(state_store=store)

        tracker.start_job("TestNet")
        started_phase_at = tracker.status.phase_started_at
        started_updated_at = tracker.status.updated_at
        assert started_phase_at is not None
        assert started_updated_at is not None

        time.sleep(0.01)
        tracker.transition(UpdatePhase.downloading)

        assert tracker.status.phase == UpdatePhase.downloading
        assert tracker.status.phase_started_at is not None
        assert tracker.status.updated_at is not None
        assert tracker.status.phase_started_at > started_phase_at
        assert tracker.status.updated_at >= tracker.status.phase_started_at

    def test_tracker_persists_runtime_logs_and_bulk_issues_immediately(
        self,
        tmp_path: Path,
    ) -> None:
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        tracker = UpdateStatusTracker(state_store=store)

        tracker.start_job("TestNet")
        tracker.set_runtime({"version": "1.2.3"})
        tracker.log("runtime collected")
        tracker.extend_issues(
            [
                UpdateIssue(
                    phase="diagnostics",
                    message="Wi-Fi warning",
                    detail="dns probe failed once",
                ),
            ],
        )

        loaded = store.load()
        assert loaded is not None
        assert loaded.runtime == {"version": "1.2.3"}
        assert loaded.updated_at is not None
        assert loaded.log_tail[-1] == "runtime collected"
        assert loaded.issues[-1].message == "Wi-Fi warning"

    @pytest.mark.asyncio
    async def test_state_persisted_on_start(self, update_env) -> None:
        """Calling start() persists the initial running status."""
        _, store, runner, make_mgr = update_env
        runner.set_response("sudo -n true", 0)
        runner.set_response("nmcli", 1, "", "not available")
        mgr = make_mgr()

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "")
            loaded = store.load()
            assert loaded is not None
            assert loaded.state == UpdateState.running
            if mgr._task is not None:
                mgr._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await mgr._task

    @pytest.mark.asyncio
    async def test_state_persisted_after_job_ends(self, update_env) -> None:
        """After the update job finishes, the final state is persisted."""
        _, store, runner, make_mgr = update_env
        runner.set_response("sudo -n true", 1, "", "no sudo")
        mgr = make_mgr()

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        loaded = store.load()
        assert loaded is not None
        assert loaded.state == UpdateState.failed
        assert loaded.finished_at is not None

    @pytest.mark.asyncio
    async def test_manager_loads_persisted_state_on_init(self, update_env) -> None:
        """A new UpdateManager instance loads previously persisted state."""
        _, store, _, make_mgr = update_env

        store.save(
            UpdateJobStatus(
                state=UpdateState.success,
                phase=UpdatePhase.done,
                started_at=1700000000.0,
                finished_at=1700000120.0,
                last_success_at=1700000120.0,
                ssid="DoneNet",
                exit_code=0,
            ),
        )
        mgr = make_mgr()

        assert mgr.status.state == UpdateState.success
        assert mgr.status.phase == UpdatePhase.done
        assert mgr.status.ssid == "DoneNet"
        assert mgr.status.exit_code == 0
