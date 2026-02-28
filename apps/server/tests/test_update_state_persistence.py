"""Tests for update state persistence and interrupted-job recovery."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.update_manager import (
    CommandRunner,
    UpdateIssue,
    UpdateJobStatus,
    UpdateManager,
    UpdatePhase,
    UpdateState,
    UpdateStateStore,
)

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
# UpdateJobStatus round-trip (to_dict / from_dict)
# ---------------------------------------------------------------------------


class TestUpdateJobStatusRoundTrip:
    def test_idle_round_trip(self) -> None:
        status = UpdateJobStatus()
        d = status.to_dict()
        restored = UpdateJobStatus.from_dict(d)
        assert restored.state == UpdateState.idle
        assert restored.phase == UpdatePhase.idle
        assert restored.issues == []
        assert restored.log_tail == []

    def test_full_status_round_trip(self) -> None:
        status = UpdateJobStatus(
            state=UpdateState.failed,
            phase=UpdatePhase.installing,
            started_at=1700000000.0,
            finished_at=1700000120.0,
            last_success_at=1699999000.0,
            ssid="MyNetwork",
            issues=[
                UpdateIssue(phase="installing", message="Wheel failed", detail="rc=1"),
                UpdateIssue(phase="restoring_hotspot", message="No AP"),
            ],
            log_tail=["line1", "line2", "line3"],
            exit_code=1,
            runtime={"version": "1.0.0"},
        )
        d = status.to_dict()
        restored = UpdateJobStatus.from_dict(d)
        assert restored.state == UpdateState.failed
        assert restored.phase == UpdatePhase.installing
        assert restored.started_at == 1700000000.0
        assert restored.finished_at == 1700000120.0
        assert restored.last_success_at == 1699999000.0
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
        assert len(loaded.issues) == 1
        assert loaded.issues[0].message == "ok"
        assert loaded.log_tail == ["log entry 1"]

    def test_load_missing_file_returns_none(self, tmp_path: Path) -> None:
        store = UpdateStateStore(path=tmp_path / "nonexistent.json")
        assert store.load() is None

    def test_load_corrupted_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("{this is not valid json}", encoding="utf-8")
        store = UpdateStateStore(path=path)
        loaded = store.load()
        assert loaded is None

    def test_load_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("", encoding="utf-8")
        store = UpdateStateStore(path=path)
        assert store.load() is None

    def test_load_invalid_state_value_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text('{"state": "bogus", "phase": "idle"}', encoding="utf-8")
        store = UpdateStateStore(path=path)
        assert store.load() is None

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
        files = list(tmp_path.iterdir())
        assert files == [path]


# ---------------------------------------------------------------------------
# No secrets in persisted file
# ---------------------------------------------------------------------------


class TestNoSecretsInPersistedFile:
    @pytest.mark.asyncio
    async def test_password_not_in_persisted_json(self, tmp_path: Path) -> None:
        """Wi-Fi password must never appear in the persisted status file."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        secret_password = "SuperSecret!WiFi#Password42"

        # Start will persist the status. The password should NOT be in the file.
        def _mock_which(n: str) -> str | None:
            return f"/usr/bin/{n}" if n in ("nmcli", "python3") else None

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", secret_password)
            assert mgr._task is not None
            # Wait for the task to complete (it will fail quickly - no real tools)
            try:
                await asyncio.wait_for(mgr._task, timeout=15)
            except (TimeoutError, asyncio.CancelledError):
                pass

        # Check every persisted file for the password
        assert state_path.is_file(), "State file should have been created"
        contents = state_path.read_text(encoding="utf-8")
        assert secret_password not in contents, "Password leaked into persisted state file!"


# ---------------------------------------------------------------------------
# Startup recovery for interrupted jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStartupRecovery:
    async def test_interrupted_running_job_becomes_failed(self, tmp_path: Path) -> None:
        """A persisted running job (no finished_at) is marked failed on startup."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)

        # Simulate a crash: write state as "running" with no finished_at
        interrupted = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.installing,
            started_at=time.time() - 60,
            ssid="CrashNet",
            log_tail=["some log"],
        )
        store.save(interrupted)

        runner = FakeRunner()
        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        # Verify the status was loaded from disk
        assert mgr.status.state == UpdateState.running

        # Run startup recovery
        await mgr.startup_recover()

        # Now the status should be failed
        assert mgr.status.state == UpdateState.failed
        assert mgr.status.finished_at is not None
        # Should have an interrupted issue
        issue_messages = [i.message for i in mgr.status.issues]
        assert any("interrupted" in m.lower() or "restart" in m.lower() for m in issue_messages)

        # Verify the failed state was persisted
        reloaded = store.load()
        assert reloaded is not None
        assert reloaded.state == UpdateState.failed
        assert reloaded.finished_at is not None

    async def test_idle_status_no_recovery_needed(self, tmp_path: Path) -> None:
        """An idle persisted status should not trigger recovery."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        store.save(UpdateJobStatus())

        runner = FakeRunner()
        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        await mgr.startup_recover()
        assert mgr.status.state == UpdateState.idle
        assert mgr.status.finished_at is None

    async def test_finished_running_job_no_recovery(self, tmp_path: Path) -> None:
        """A running job WITH finished_at set does not trigger recovery."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        finished = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.done,
            started_at=time.time() - 60,
            finished_at=time.time() - 30,
        )
        store.save(finished)

        runner = FakeRunner()
        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        await mgr.startup_recover()
        # Should NOT add an interrupted issue
        issue_messages = [i.message for i in mgr.status.issues]
        assert not any("interrupted" in m.lower() for m in issue_messages)

    async def test_recovery_attempts_network_cleanup(self, tmp_path: Path) -> None:
        """Startup recovery attempts to clean up uplink and restore hotspot."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        interrupted = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.connecting_wifi,
            started_at=time.time() - 60,
        )
        store.save(interrupted)

        runner = FakeRunner()
        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        await mgr.startup_recover()

        # Should have tried nmcli commands for cleanup
        all_args = [" ".join(c[0]) for c in runner.calls]
        # cleanup_uplink does "connection down" and "connection delete"
        assert any("connection down" in a for a in all_args)
        assert any("connection delete" in a for a in all_args)
        # restore_hotspot does "connection up"
        assert any("connection up" in a for a in all_args)

    async def test_recovery_handles_nmcli_failure_gracefully(self, tmp_path: Path) -> None:
        """If nmcli fails during recovery, it adds issues but doesn't crash."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        interrupted = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.downloading,
            started_at=time.time() - 60,
        )
        store.save(interrupted)

        runner = FakeRunner()
        # All nmcli commands fail
        runner.default_response = (1, "", "nmcli not found")
        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        await mgr.startup_recover()

        # Should still be marked as failed (not crash)
        assert mgr.status.state == UpdateState.failed
        assert mgr.status.finished_at is not None


# ---------------------------------------------------------------------------
# Persistence during update lifecycle
# ---------------------------------------------------------------------------


class TestPersistenceDuringLifecycle:
    @pytest.mark.asyncio
    async def test_state_persisted_on_start(self, tmp_path: Path) -> None:
        """Calling start() persists the initial running status."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        # Make nmcli fail fast so the update ends quickly
        runner.set_response("nmcli", 1, "", "not available")

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        def _mock_which(n: str) -> str | None:
            return f"/usr/bin/{n}" if n in ("nmcli", "python3") else None

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "")
            # Status should be persisted immediately after start
            loaded = store.load()
            assert loaded is not None
            assert loaded.state == UpdateState.running

    @pytest.mark.asyncio
    async def test_state_persisted_after_job_ends(self, tmp_path: Path) -> None:
        """After the update job finishes, the final state is persisted."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)
        runner = FakeRunner()
        # No sudo available → validating will fail
        runner.set_response("sudo -n true", 1, "", "no sudo")

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        def _mock_which(n: str) -> str | None:
            return f"/usr/bin/{n}" if n in ("nmcli", "python3") else None

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        loaded = store.load()
        assert loaded is not None
        assert loaded.state == UpdateState.failed
        assert loaded.finished_at is not None

    @pytest.mark.asyncio
    async def test_manager_loads_persisted_state_on_init(self, tmp_path: Path) -> None:
        """A new UpdateManager instance loads previously persisted state."""
        state_path = tmp_path / "state.json"
        store = UpdateStateStore(path=state_path)

        # Persist a success state
        success_status = UpdateJobStatus(
            state=UpdateState.success,
            phase=UpdatePhase.done,
            started_at=1700000000.0,
            finished_at=1700000120.0,
            last_success_at=1700000120.0,
            ssid="DoneNet",
            exit_code=0,
        )
        store.save(success_status)

        # Create a new manager → should load the persisted state
        mgr = UpdateManager(
            runner=FakeRunner(),
            repo_path=str(tmp_path / "repo"),
            rollback_dir=str(tmp_path / "rollback"),
            state_store=store,
        )

        assert mgr.status.state == UpdateState.success
        assert mgr.status.phase == UpdatePhase.done
        assert mgr.status.ssid == "DoneNet"
        assert mgr.status.exit_code == 0
