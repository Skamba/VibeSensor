from __future__ import annotations

from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRuntimeDetails,
    UpdateState,
)
from vibesensor.use_cases.updates.runner import sanitize_log_line as sanitize_log_line
from vibesensor.use_cases.updates.venv_paths import (
    is_reinstall_venv_ready,
    reinstall_python_executable,
)


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
        assert data["runtime"] == UpdateRuntimeDetails().to_payload()

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
        assert reinstall_python_executable(repo) == str(venv_python)

    def test_reinstall_python_uses_server_venv_path_even_if_missing(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        expected = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        assert reinstall_python_executable(repo) == str(expected)

    def test_reinstall_venv_readiness_requires_pyvenv_cfg(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        venv_python = repo / "apps" / "server" / ".venv" / "bin" / "python3"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/usr/bin/env python3\n")
        venv_python.chmod(0o755)
        assert not is_reinstall_venv_ready(repo)
        (repo / "apps" / "server" / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
        assert is_reinstall_venv_ready(repo)


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
