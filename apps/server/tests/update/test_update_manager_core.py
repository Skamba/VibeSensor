from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from _update_manager_test_helpers import FakeRunner, cancel_task, mock_which

from vibesensor.update.manager import UpdateManager
from vibesensor.update.models import UpdatePhase, UpdateState


class TestUpdateManager:
    def make_manager(self, *, runner: FakeRunner | None = None) -> tuple[UpdateManager, FakeRunner]:
        active_runner = runner or FakeRunner()
        manager = UpdateManager(runner=active_runner, repo_path="/tmp/fakerepo")
        return manager, active_runner

    def test_initial_status_is_idle(self) -> None:
        manager, _ = self.make_manager()
        assert manager.status.state == UpdateState.idle
        assert manager.status.phase == UpdatePhase.idle

    def test_start_validates_ssid(self) -> None:
        manager, _ = self.make_manager()
        with pytest.raises(ValueError, match="SSID"):
            manager.start("", "pw")
        with pytest.raises(ValueError, match="SSID"):
            manager.start("   ", "pw")
        with pytest.raises(ValueError, match="SSID"):
            manager.start("x" * 65, "pw")

    def test_start_validates_password_length(self) -> None:
        manager, _ = self.make_manager()
        with pytest.raises(ValueError, match="Password"):
            manager.start("TestNet", "p" * 129)

    @pytest.mark.asyncio
    async def test_concurrent_start_rejection(self) -> None:
        runner = FakeRunner()
        original_run = runner.run
        hang = asyncio.Event()

        async def slow_run(args, *, timeout=30, env=None):
            if "fetch" in " ".join(args):
                await hang.wait()
                return (0, "", "")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = slow_run  # type: ignore[assignment]
        runner.set_response("sudo -n true", 0)
        manager = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        with patch("shutil.which", mock_which):
            manager.start("TestNet", "pass123")
            assert manager.status.state == UpdateState.running
            with pytest.raises(RuntimeError, match="already in progress"):
                manager.start("OtherNet", "pass456")

        manager.cancel()
        await cancel_task(manager)

    def test_cancel_returns_false_when_idle(self) -> None:
        manager, _ = self.make_manager()
        assert manager.cancel() is False

    @pytest.mark.asyncio
    async def test_cancel_returns_true_when_running(self) -> None:
        runner = FakeRunner()
        original_run = runner.run
        hang = asyncio.Event()

        async def slow_run(args, *, timeout=30, env=None):
            if "fetch" in " ".join(args):
                await hang.wait()
                return (0, "", "")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = slow_run  # type: ignore[assignment]
        runner.set_response("sudo -n true", 0)
        manager = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        with patch("shutil.which", mock_which):
            manager.start("TestNet", "pass")
            assert manager.cancel() is True

        await cancel_task(manager)

    @pytest.mark.asyncio
    async def test_status_to_dict_never_leaks_password(self) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        manager = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        with patch("shutil.which", mock_which):
            manager.start("TestNet", "supersecret")

        assert "supersecret" not in str(manager.status.to_dict())
        await cancel_task(manager)

    @pytest.mark.asyncio
    async def test_start_sets_ssid_and_timestamps(self) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        manager = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        before = time.time()
        with patch("shutil.which", mock_which):
            manager.start("MyWifi", "pw")
        after = time.time()

        assert manager.status.ssid == "MyWifi"
        assert before <= manager.status.started_at <= after
        await cancel_task(manager)