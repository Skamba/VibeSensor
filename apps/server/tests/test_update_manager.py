"""Tests for update_manager module."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from vibesensor.update_manager import (
    CommandRunner,
    UpdateIssue,
    UpdateJobStatus,
    UpdateManager,
    UpdatePhase,
    UpdateState,
    _sanitize_log_line,
    parse_wifi_diagnostics,
)

# ---------------------------------------------------------------------------
# Fake command runner for tests
# ---------------------------------------------------------------------------


class FakeRunner(CommandRunner):
    """Test double that returns pre-configured responses."""

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


def _mock_which(name: str) -> str | None:
    """Pretend required update tools exist."""
    if name in ("nmcli", "python3"):
        return f"/usr/bin/{name}"
    return None


def _seed_runtime_artifacts(repo: Path, mgr: UpdateManager, *, valid: bool = True) -> None:
    (repo / "apps" / "ui" / "src").mkdir(parents=True, exist_ok=True)
    (repo / "apps" / "server").mkdir(parents=True, exist_ok=True)
    (repo / "apps" / "server" / "public").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    (repo / "tools" / "sync_ui_to_pi_public.py").write_text("#!/usr/bin/env python3\n")
    (repo / "apps" / "server" / "pyproject.toml").write_text("[project]\nname='vibesensor'\n")
    (repo / "apps" / "ui" / "src" / "main.ts").write_text("console.log('ui')\n")
    (repo / "apps" / "ui" / "package.json").write_text('{"name":"ui"}\n')
    (repo / "apps" / "ui" / "package-lock.json").write_text('{"name":"ui","lockfileVersion":3}\n')
    (repo / "apps" / "server" / "public" / "index.html").write_text("<html>ok</html>\n")
    details = mgr._collect_runtime_details()
    metadata = {
        "ui_source_hash": details["ui_source_hash"] if valid else "stale-source-hash",
        "public_assets_hash": details["public_assets_hash"],
        "git_commit": "deadbeef",
    }
    (repo / "apps" / "server" / "public" / ".vibesensor-ui-build.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# UpdateJobStatus
# ---------------------------------------------------------------------------


class TestUpdateJobStatus:
    def test_default_status_to_dict(self) -> None:
        status = UpdateJobStatus()
        d = status.to_dict()
        assert d["state"] == "idle"
        assert d["phase"] == "idle"
        assert d["started_at"] is None
        assert d["finished_at"] is None
        assert d["last_success_at"] is None
        assert d["ssid"] == ""
        assert d["issues"] == []
        assert d["log_tail"] == []
        assert d["exit_code"] is None
        assert d["runtime"] == {}

    def test_status_with_issues(self) -> None:
        status = UpdateJobStatus(
            state=UpdateState.failed,
            phase=UpdatePhase.installing,
            ssid="TestNet",
            issues=[UpdateIssue(phase="installing", message="Install failed", detail="rc=1")],
        )
        d = status.to_dict()
        assert d["state"] == "failed"
        assert d["ssid"] == "TestNet"
        assert len(d["issues"]) == 1
        assert d["issues"][0]["phase"] == "installing"
        assert d["issues"][0]["message"] == "Install failed"

    def test_log_tail_truncated(self) -> None:
        status = UpdateJobStatus(log_tail=[f"line {i}" for i in range(100)])
        d = status.to_dict()
        assert len(d["log_tail"]) == 50  # max 50 in serialization


class TestUpdaterInterpreterSelection:
    def test_reinstall_python_prefers_server_venv_python3(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        venv_python = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n")
        os.chmod(venv_python, 0o755)
        (repo / "apps" / "server" / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
        assert UpdateManager._reinstall_python_executable(repo) == str(venv_python)

    def test_reinstall_python_uses_server_venv_path_even_if_missing(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        expected = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        assert UpdateManager._reinstall_python_executable(repo) == str(expected)

    def test_reinstall_venv_readiness_requires_pyvenv_cfg(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        venv_python = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n")
        os.chmod(venv_python, 0o755)
        assert not UpdateManager._is_reinstall_venv_ready(repo)
        (repo / "apps" / "server" / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
        assert UpdateManager._is_reinstall_venv_ready(repo)


# ---------------------------------------------------------------------------
# sanitize_log_line
# ---------------------------------------------------------------------------


class TestSanitizeLogLine:
    def test_sanitizes_password(self) -> None:
        line = "psk=mysecretpassword123"
        result = _sanitize_log_line(line)
        assert "mysecretpassword123" not in result
        assert "psk=***" in result

    def test_sanitizes_key(self) -> None:
        line = "key: verysecret"
        result = _sanitize_log_line(line)
        assert "verysecret" not in result

    def test_truncates_long_lines(self) -> None:
        line = "x" * 1000
        result = _sanitize_log_line(line)
        assert len(result) <= 500

    def test_normal_line_unchanged(self) -> None:
        line = "Hotspot restored on attempt 1"
        result = _sanitize_log_line(line)
        assert result == line


# ---------------------------------------------------------------------------
# parse_wifi_diagnostics
# ---------------------------------------------------------------------------


class TestParseWifiDiagnostics:
    def test_no_log_dir(self, tmp_path) -> None:
        issues = parse_wifi_diagnostics(str(tmp_path / "nonexistent"))
        assert issues == []

    def test_summary_failure(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "summary.txt").write_text("status=FAILED\nrc=22\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        assert len(issues) >= 1
        assert any("failure" in i.message.lower() for i in issues)

    def test_hotspot_log_errors(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "hotspot.log").write_text(
            "2024-01-01 INFO normaline\n2024-01-01 ERROR something failed\n2024-01-01 INFO ok\n"
        )
        issues = parse_wifi_diagnostics(str(log_dir))
        assert len(issues) >= 1
        assert any("error" in i.detail.lower() or "failed" in i.detail.lower() for i in issues)

    def test_password_not_leaked_in_diagnostics(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "hotspot.log").write_text("ERROR psk=hunter2 failed\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        for issue in issues:
            assert "hunter2" not in issue.detail
            assert "hunter2" not in issue.message


# ---------------------------------------------------------------------------
# UpdateManager - unit tests
# ---------------------------------------------------------------------------


class TestUpdateManager:
    def _make_manager(
        self,
        *,
        runner: FakeRunner | None = None,
    ) -> tuple[UpdateManager, FakeRunner]:
        r = runner or FakeRunner()
        mgr = UpdateManager(
            runner=r,
            repo_path="/tmp/fakerepo",
            git_remote="https://example.com/repo.git",
            git_branch="main",
        )
        return mgr, r

    def test_initial_status_is_idle(self) -> None:
        mgr, _ = self._make_manager()
        assert mgr.status.state == UpdateState.idle
        assert mgr.status.phase == UpdatePhase.idle

    def test_start_validates_ssid(self) -> None:
        mgr, _ = self._make_manager()
        with pytest.raises(ValueError, match="SSID"):
            mgr.start("", "pw")
        with pytest.raises(ValueError, match="SSID"):
            mgr.start("   ", "pw")
        with pytest.raises(ValueError, match="SSID"):
            mgr.start("x" * 65, "pw")

    def test_start_validates_password_length(self) -> None:
        mgr, _ = self._make_manager()
        with pytest.raises(ValueError, match="Password"):
            mgr.start("TestNet", "p" * 129)

    @pytest.mark.asyncio
    async def test_concurrent_start_rejection(self) -> None:
        runner = FakeRunner()
        original_run = runner.run
        _hang = asyncio.Event()

        async def slow_run(args, *, timeout=30, env=None):
            if "fetch" in " ".join(args):
                await _hang.wait()  # block until cancelled
                return (0, "", "")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = slow_run  # type: ignore[assignment]
        runner.set_response("sudo -n true", 0)
        mgr = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "pass123")
            assert mgr.status.state == UpdateState.running
            with pytest.raises(RuntimeError, match="already in progress"):
                mgr.start("OtherNet", "pass456")

        mgr.cancel()
        if mgr._task:
            mgr._task.cancel()
            try:
                await mgr._task
            except (asyncio.CancelledError, Exception):
                pass

    def test_cancel_returns_false_when_idle(self) -> None:
        mgr, _ = self._make_manager()
        assert mgr.cancel() is False

    @pytest.mark.asyncio
    async def test_cancel_returns_true_when_running(self) -> None:
        runner = FakeRunner()
        original_run = runner.run
        _hang = asyncio.Event()

        async def slow_run(args, *, timeout=30, env=None):
            if "fetch" in " ".join(args):
                await _hang.wait()  # block until cancelled
                return (0, "", "")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = slow_run  # type: ignore[assignment]
        runner.set_response("sudo -n true", 0)
        mgr = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "pass")
            assert mgr.cancel() is True

        if mgr._task:
            mgr._task.cancel()
            try:
                await mgr._task
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_status_to_dict_never_leaks_password(self) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        mgr = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "supersecret")

        d = mgr.status.to_dict()
        serialized = str(d)
        assert "supersecret" not in serialized

        if mgr._task:
            mgr._task.cancel()
            try:
                await mgr._task
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_start_sets_ssid_and_timestamps(self) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        mgr = UpdateManager(runner=runner, repo_path="/tmp/fakerepo")

        before = time.time()
        with patch("shutil.which", _mock_which):
            mgr.start("MyWifi", "pw")
        after = time.time()

        assert mgr.status.ssid == "MyWifi"
        assert mgr.status.started_at is not None
        assert before <= mgr.status.started_at <= after

        if mgr._task:
            mgr._task.cancel()
            try:
                await mgr._task
            except (asyncio.CancelledError, Exception):
                pass


# ---------------------------------------------------------------------------
# UpdateManager - async integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateManagerAsync:
    async def test_happy_path(self, tmp_path) -> None:
        """Full update completes successfully with release-based flow."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        # Create rollback dir
        rollback_dir = tmp_path / "rollback"
        rollback_dir.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(rollback_dir),
        )
        _seed_runtime_artifacts(repo, mgr, valid=True)

        # Mock the release fetcher to return a fake release
        mock_release = MagicMock()
        mock_release.version = "2025.6.15"
        mock_release.tag = "server-v2025.6.15"
        mock_release.sha256 = "abc123"
        mock_release.asset_name = "vibesensor-2025.6.15-py3-none-any.whl"

        mock_wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
        mock_wheel_path.write_text("fake-wheel")

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.14"),
        ):
            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = mock_release
            mock_fetcher_inst.download_wheel.return_value = mock_wheel_path

            # Mock the installed version check (post-install verification)
            runner.set_response("from vibesensor import __version__", 0, "2025.6.15", "")

            mgr.start("TestNet", "pass123")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.success
        assert mgr.status.phase == UpdatePhase.done
        assert mgr.status.finished_at is not None
        assert mgr.status.last_success_at is not None
        assert mgr.status.exit_code == 0

        # Verify pip install was called with the wheel
        pip_install_calls = [
            c[0]
            for c in runner.calls
            if "pip" in " ".join(c[0])
            and "install" in " ".join(c[0])
            and "vibesensor" in " ".join(c[0])
        ]
        assert pip_install_calls, "Expected pip install with wheel"

        # Verify hotspot restore was attempted
        restore_calls = [
            c for c in runner.calls if "VibeSensor-AP" in " ".join(c[0]) and "up" in " ".join(c[0])
        ]
        assert len(restore_calls) > 0

        # Verify service restart was scheduled
        restart_cmd = (
            "systemd-run --unit vibesensor-post-update-restart --on-active=2s "
            "systemctl restart vibesensor.service"
        )
        assert any(restart_cmd in " ".join(c[0]) for c in runner.calls)

    async def test_already_up_to_date(self, tmp_path) -> None:
        """When already up-to-date, skip install and succeed."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )
        _seed_runtime_artifacts(repo, mgr, valid=True)

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.15"),
        ):
            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = None

            mgr.start("TestNet", "pass123")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.success

        # No pip install calls should have been made
        pip_install_calls = [
            c[0]
            for c in runner.calls
            if "pip" in " ".join(c[0])
            and "install" in " ".join(c[0])
            and "force-reinstall" in " ".join(c[0])
        ]
        assert not pip_install_calls, "Should not install when already up-to-date"

    async def test_no_sudo_fails_gracefully(self, tmp_path) -> None:
        """When sudo is unavailable, update fails with clear issue."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 1, "", "sudo: a password is required")

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(runner=runner, repo_path=str(repo))

        with patch("shutil.which", _mock_which):
            mgr.start("TestNet", "pass")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(f"{i.message} {i.detail}" for i in mgr.status.issues).lower()
        assert "privileg" in issues_text

    async def test_wifi_connection_failure(self, tmp_path) -> None:
        """When Wi-Fi connection fails, hotspot is restored."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        runner.set_response(
            "connection up VibeSensor-Uplink",
            1,
            "",
            "Error: Connection activation failed",
        )

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with patch("shutil.which", _mock_which):
            mgr.start("BadNet", "wrong")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(i.message for i in mgr.status.issues).lower()
        assert "connect" in issues_text or "wi-fi" in issues_text

        restore_calls = [
            c for c in runner.calls if "VibeSensor-AP" in " ".join(c[0]) and "up" in " ".join(c[0])
        ]
        assert len(restore_calls) > 0

    async def test_wifi_ssid_not_found_retries_then_succeeds(self, tmp_path) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()
        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )
        _seed_runtime_artifacts(repo, mgr, valid=True)

        original_run = runner.run
        connect_calls = {"count": 0}

        async def run_with_retry(args, *, timeout=30, env=None):
            joined = " ".join(args)
            if "connection up VibeSensor-Uplink" in joined:
                connect_calls["count"] += 1
                if connect_calls["count"] == 1:
                    return (10, "", "Error: No network with SSID 'TestNet' found.\n")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = run_with_retry  # type: ignore[assignment]

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.15"),
        ):
            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = None

            mgr.start("TestNet", "pass123")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.success
        assert connect_calls["count"] >= 2
        rescan_calls = [
            c
            for c in runner.calls
            if len(c[0]) >= 6
            and c[0][0] == "sudo"
            and "dev wifi list" in " ".join(c[0])
            and "--rescan yes" in " ".join(c[0])
        ]
        assert rescan_calls, "Expected updater to rescan Wi-Fi after SSID-not-found"

    async def test_dns_not_ready_fails_with_clear_issue(self, tmp_path) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        runner.set_response("socket.getaddrinfo", 1, "", "Temporary failure in name resolution")

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.update_manager.DNS_READY_MIN_WAIT_S", 0.05),
            patch("vibesensor.update_manager.DNS_RETRY_INTERVAL_S", 0.01),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.15"),
        ):
            mgr.start("TestNet", "pass123")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

            MockFetcher.assert_not_called()

        assert mgr.status.state == UpdateState.failed
        issues_blob = " ".join(
            f"{issue.message} {issue.detail}" for issue in mgr.status.issues
        ).lower()
        assert "dns" in issues_blob
        assert "waited at least" in issues_blob

    async def test_dns_probe_retries_then_update_continues(self, tmp_path) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )
        _seed_runtime_artifacts(repo, mgr, valid=True)

        original_run = runner.run
        probe_attempts = {"count": 0}

        async def run_with_dns_retry(args, *, timeout=30, env=None):
            joined = " ".join(args)
            if "socket.getaddrinfo" in joined:
                probe_attempts["count"] += 1
                if probe_attempts["count"] < 3:
                    return (1, "", "Temporary failure in name resolution")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = run_with_dns_retry  # type: ignore[assignment]

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.update_manager.DNS_READY_MIN_WAIT_S", 0.2),
            patch("vibesensor.update_manager.DNS_RETRY_INTERVAL_S", 0.01),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.15"),
        ):
            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = None

            mgr.start("TestNet", "pass123")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.success
        assert probe_attempts["count"] >= 3

    async def test_secure_ssid_requires_password(self, tmp_path) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        runner.set_response("dev wifi list", 0, "Pim:WPA2\n")

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with patch("shutil.which", _mock_which):
            mgr.start("Pim", "")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(i.message.lower() for i in mgr.status.issues)
        assert "password required" in issues_text
        assert not any("connection up VibeSensor-Uplink" in " ".join(c[0]) for c in runner.calls)

    async def test_password_is_applied_via_connection_modify(self, tmp_path) -> None:
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )
        _seed_runtime_artifacts(repo, mgr, valid=True)

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.15"),
        ):
            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = None

            mgr.start("Pim", "tomaat123")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        joined_calls = [" ".join(c[0]) for c in runner.calls]
        assert any(
            "connection modify VibeSensor-Uplink wifi-sec.key-mgmt wpa-psk wifi-sec.psk" in call
            for call in joined_calls
        )

    async def test_download_failure_still_restores_hotspot(self, tmp_path) -> None:
        """When release download fails, hotspot is still restored."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.14"),
        ):
            mock_release = MagicMock()
            mock_release.version = "2025.6.15"
            mock_release.tag = "server-v2025.6.15"
            mock_release.sha256 = "abc"

            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = mock_release
            mock_fetcher_inst.download_wheel.side_effect = OSError("Network error")

            mgr.start("TestNet", "pass")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        restore_calls = [
            c for c in runner.calls if "VibeSensor-AP" in " ".join(c[0]) and "up" in " ".join(c[0])
        ]
        assert len(restore_calls) > 0

    async def test_install_failure_triggers_rollback(self, tmp_path) -> None:
        """When pip install fails, rollback is attempted and hotspot restored."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)
        # Make pip install fail
        runner.set_response("pip", 1, "", "ERROR: Could not install")

        repo = tmp_path / "repo"
        repo.mkdir()
        rollback_dir = tmp_path / "rollback"
        rollback_dir.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(rollback_dir),
        )

        fake_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
        fake_wheel.write_text("fake-wheel")

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.14"),
        ):
            mock_release = MagicMock()
            mock_release.version = "2025.6.15"
            mock_release.tag = "server-v2025.6.15"
            mock_release.sha256 = "abc"

            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = mock_release
            mock_fetcher_inst.download_wheel.return_value = fake_wheel

            mgr.start("TestNet", "pass")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(i.message.lower() for i in mgr.status.issues)
        assert "install" in issues_text

    async def test_password_never_in_logs(self, tmp_path) -> None:
        """Password must never appear in status log_tail or issues."""
        secret = "SuperSecret!Password#2024"
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.15"),
        ):
            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.return_value = None

            mgr.start("TestNet", secret)
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        serialized = str(mgr.status.to_dict())
        assert secret not in serialized

        for line in mgr.status.log_tail:
            assert secret not in line
        for issue in mgr.status.issues:
            assert secret not in issue.message
            assert secret not in issue.detail

    async def test_stale_public_assets_detected_in_runtime(self, tmp_path) -> None:
        """Runtime details report assets_verified=False when legacy public/ hashes mismatch."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()
        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )
        _seed_runtime_artifacts(repo, mgr, valid=False)

        details = mgr._collect_runtime_details()
        # Without packaged static, stale hashes → not verified
        assert details["assets_verified"] is False

    async def test_timeout_handling(self, tmp_path) -> None:
        """When update times out, it fails and restores hotspot."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        original_run = runner.run

        async def slow_run(args, *, timeout=30, env=None):
            # Make the Wi-Fi connect step hang to trigger the update timeout.
            if "connection up" in " ".join(args):
                await asyncio.sleep(300)
                return (0, "", "")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = slow_run  # type: ignore[assignment]

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.update_manager.UPDATE_TIMEOUT_S", 0.5),
        ):
            mgr.start("TestNet", "pass")
            assert mgr._task is not None
            try:
                await asyncio.wait_for(mgr._task, timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                pass

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(i.message for i in mgr.status.issues).lower()
        assert "timeout" in issues_text or "timed out" in issues_text

    async def test_check_update_failure_fails_update(self, tmp_path) -> None:
        """When check_update_available raises, update fails gracefully."""
        runner = FakeRunner()
        runner.set_response("sudo -n true", 0)

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with (
            patch("shutil.which", _mock_which),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as MockFetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.14"),
        ):
            mock_fetcher_inst = MockFetcher.return_value
            mock_fetcher_inst.check_update_available.side_effect = RuntimeError(
                "API rate limit exceeded"
            )

            mgr.start("TestNet", "pass")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(i.message.lower() for i in mgr.status.issues)
        assert "check" in issues_text or "update" in issues_text

    async def test_missing_tools_fails_gracefully(self, tmp_path) -> None:
        """When nmcli is not found, update fails with clear issue."""
        runner = FakeRunner()

        def no_nmcli(name: str) -> str | None:
            if name == "nmcli":
                return None
            return f"/usr/bin/{name}"

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(runner=runner, repo_path=str(repo))

        with patch("shutil.which", no_nmcli):
            mgr.start("TestNet", "pass")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(i.message for i in mgr.status.issues).lower()
        assert "nmcli" in issues_text

    async def test_missing_python3_fails_gracefully(self, tmp_path) -> None:
        """When python3 is not found, update fails with clear issue."""
        runner = FakeRunner()

        def no_python3(name: str) -> str | None:
            if name == "python3":
                return None
            return f"/usr/bin/{name}"

        repo = tmp_path / "repo"
        repo.mkdir()

        mgr = UpdateManager(runner=runner, repo_path=str(repo))

        with patch("shutil.which", no_python3):
            mgr.start("TestNet", "pass")
            assert mgr._task is not None
            await asyncio.wait_for(mgr._task, timeout=10)

        assert mgr.status.state == UpdateState.failed
        issues_text = " ".join(i.message for i in mgr.status.issues).lower()
        assert "python3" in issues_text

    async def test_ensure_contracts_env_dropin_reload_when_changed(self, tmp_path) -> None:
        runner = FakeRunner()
        runner.set_response("python3 -c", 0, "changed", "")

        repo = tmp_path / "repo"
        repo.mkdir()
        contracts_dir = tmp_path / "contracts"
        contracts_dir.mkdir()

        mgr = UpdateManager(
            runner=runner,
            repo_path=str(repo),
            rollback_dir=str(tmp_path / "rollback"),
        )

        with (
            patch(
                "vibesensor.update_manager.SERVICE_CONTRACTS_DIR",
                str(contracts_dir),
            ),
            patch(
                "vibesensor.update_manager.SERVICE_ENV_DROPIN",
                str(tmp_path / "10-contracts-dir.conf"),
            ),
        ):
            await mgr._ensure_service_contracts_env()

        joined_calls = [" ".join(c[0]) for c in runner.calls]
        assert any("python3 -c" in call for call in joined_calls)
        assert any("systemctl daemon-reload" in call for call in joined_calls)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestUpdateApiEndpoints:
    """Test the update API endpoints via the router."""

    def test_status_endpoint_exists(self) -> None:
        """Verify the update status route is registered."""
        from unittest.mock import MagicMock

        from vibesensor.api import create_router

        state = MagicMock()
        state.update_manager = UpdateManager()
        router = create_router(state)

        paths = [route.path for route in router.routes]
        assert "/api/settings/update/status" in paths
        assert "/api/settings/update/start" in paths
        assert "/api/settings/update/cancel" in paths

    def test_start_request_model_validation(self) -> None:
        """Verify the request model validates SSID/password."""
        from vibesensor.api import UpdateStartRequest

        # Valid
        req = UpdateStartRequest(ssid="TestNet", password="pass123")
        assert req.ssid == "TestNet"

        # Empty SSID should fail
        with pytest.raises(ValidationError):
            UpdateStartRequest(ssid="", password="pass")

        # SSID too long should fail
        with pytest.raises(ValidationError):
            UpdateStartRequest(ssid="x" * 65, password="pass")

        # Password too long should fail
        with pytest.raises(ValidationError):
            UpdateStartRequest(ssid="Net", password="x" * 129)

        # No password is fine (open network)
        req = UpdateStartRequest(ssid="OpenNet")
        assert req.password == ""
