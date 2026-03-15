from __future__ import annotations

from pathlib import Path

from vibesensor.domain.updates.models import UpdateIssue, UpdateJobStatus, UpdatePhase, UpdateState
from vibesensor.use_cases.updates.installer import UpdateInstaller
from vibesensor.use_cases.updates.runner import sanitize_log_line as sanitize_log_line
from vibesensor.use_cases.updates.wifi import parse_wifi_diagnostics


class TestUpdateJobStatus:
    def test_default_status_to_dict(self) -> None:
        status = UpdateJobStatus()
        data = status.to_dict()
        assert data["state"] == "idle"
        assert data["phase"] == "idle"
        assert data["started_at"] is None
        assert data["finished_at"] is None
        assert data["last_success_at"] is None
        assert data["ssid"] == ""
        assert data["issues"] == []
        assert data["log_tail"] == []
        assert data["exit_code"] is None
        assert data["runtime"] == {}

    def test_status_with_issues(self) -> None:
        status = UpdateJobStatus(
            state=UpdateState.failed,
            phase=UpdatePhase.installing,
            ssid="TestNet",
            issues=[UpdateIssue(phase="installing", message="Install failed", detail="rc=1")],
        )
        data = status.to_dict()
        assert data["state"] == "failed"
        assert data["ssid"] == "TestNet"
        assert len(data["issues"]) == 1

    def test_log_tail_truncated(self) -> None:
        status = UpdateJobStatus(log_tail=[f"line {i}" for i in range(100)])
        assert len(status.to_dict()["log_tail"]) == 50


class TestUpdaterInterpreterSelection:
    def test_reinstall_python_prefers_server_venv_python3(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        venv_python = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n")
        venv_python.chmod(0o755)
        (repo / "apps" / "server" / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
        assert UpdateInstaller.reinstall_python_executable(repo) == str(venv_python)

    def test_reinstall_python_uses_server_venv_path_even_if_missing(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        expected = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        assert UpdateInstaller.reinstall_python_executable(repo) == str(expected)

    def test_reinstall_venv_readiness_requires_pyvenv_cfg(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        venv_python = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n")
        venv_python.chmod(0o755)
        assert not UpdateInstaller.is_reinstall_venv_ready(repo)
        (repo / "apps" / "server" / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
        assert UpdateInstaller.is_reinstall_venv_ready(repo)


class TestSanitizeLogLine:
    def test_sanitizes_password(self) -> None:
        result = sanitize_log_line("psk=mysecretpassword123")
        assert "mysecretpassword123" not in result
        assert "psk=***" in result

    def test_sanitizes_key(self) -> None:
        result = sanitize_log_line("key: verysecret")
        assert "verysecret" not in result

    def test_truncates_long_lines(self) -> None:
        assert len(sanitize_log_line("x" * 1000)) <= 500

    def test_normal_line_unchanged(self) -> None:
        line = "Hotspot restored on attempt 1"
        assert sanitize_log_line(line) == line


class TestParseWifiDiagnostics:
    def test_no_log_dir(self, tmp_path) -> None:
        assert parse_wifi_diagnostics(str(tmp_path / "nonexistent")) == []

    def test_summary_failure(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "summary.txt").write_text("status=FAILED\nrc=22\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        assert any("failure" in issue.message.lower() for issue in issues)

    def test_summary_timeout_case_insensitive(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "summary.txt").write_text("status=timeout\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        assert any("timeout" in (issue.detail or "").lower() for issue in issues)

    def test_summary_password_not_leaked(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "summary.txt").write_text("status=FAILED psk=hunter2\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        for issue in issues:
            assert "hunter2" not in (issue.detail or "")

    def test_hotspot_log_errors(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "hotspot.log").write_text(
            "2024-01-01 INFO normaline\n2024-01-01 ERROR something failed\n2024-01-01 INFO ok\n",
        )
        issues = parse_wifi_diagnostics(str(log_dir))
        assert any(
            "error" in issue.detail.lower() or "failed" in issue.detail.lower() for issue in issues
        )

    def test_password_not_leaked_in_diagnostics(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "hotspot.log").write_text("ERROR psk=hunter2 failed\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        for issue in issues:
            assert "hunter2" not in issue.detail
            assert "hunter2" not in issue.message

    def test_read_errors_are_ignored(self, tmp_path, monkeypatch) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "summary.txt").write_text("status=FAILED\n")

        def raise_oserror(*_args, **_kwargs) -> str:
            raise OSError("boom")

        monkeypatch.setattr(Path, "read_text", raise_oserror)
        assert parse_wifi_diagnostics(str(log_dir)) == []
