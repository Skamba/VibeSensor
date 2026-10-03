from __future__ import annotations

import os

import vibesensor.updates.privilege as update_privilege
from vibesensor.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateState,
    UpdateTransport,
)
from vibesensor.updates.runner import sanitize_log_line as sanitize_log_line
from vibesensor.updates.status.payload_codec import update_status_to_builtins


class TestUpdateJobStatus:
    def test_default_status_to_payload(self) -> None:
        status = UpdateJobStatus()
        data = update_status_to_builtins(status)
        assert data["state"] == "idle"
        assert data["phase"] == "idle"
        assert data["started_at"] is None
        assert data["finished_at"] is None
        assert data["last_success_at"] is None
        assert data["transport"] == UpdateTransport.wifi.value
        assert data["ssid"] is None
        assert data["issues"] == []
        assert data["log_tail"] == []
        assert data["exit_code"] is None
        assert data["runtime"] == {
            "version": "",
            "commit": "",
            "ui_source_hash": "",
            "static_assets_hash": "",
            "static_build_source_hash": "",
            "static_build_commit": "",
            "assets_verified": False,
            "has_packaged_static": False,
        }

    def test_status_with_issues(self) -> None:
        status = UpdateJobStatus(
            state=UpdateState.failed,
            phase=UpdatePhase.installing,
            ssid="TestNet",
            issues=[UpdateIssue(phase="installing", message="Install failed", detail="rc=1")],
        )
        data = update_status_to_builtins(status)
        assert data["state"] == "failed"
        assert data["ssid"] == "TestNet"
        assert data["issues"] == [
            {"phase": "installing", "message": "Install failed", "detail": "rc=1"},
        ]

    def test_log_tail_truncated(self) -> None:
        status = UpdateJobStatus(log_tail=[f"line {i}" for i in range(100)])
        assert update_status_to_builtins(status)["log_tail"] == [
            f"line {i}" for i in range(50, 100)
        ]


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


class TestSudoWrapperDiscovery:
    def test_sudo_prefix_uses_explicit_wrapper_override(self, monkeypatch, tmp_path) -> None:
        wrapper = tmp_path / "custom-wrapper.sh"
        wrapper.write_text("#!/usr/bin/env bash\n")
        wrapper.chmod(0o755)

        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        monkeypatch.setenv("VIBESENSOR_UPDATE_SUDO_WRAPPER", os.fspath(wrapper))
        monkeypatch.delenv("VIBESENSOR_REPO_PATH", raising=False)
        monkeypatch.setattr(update_privilege, "_DEFAULT_INSTALL_REPO", tmp_path / "missing-install")
        monkeypatch.setattr(
            update_privilege,
            "_SOURCE_TREE_WRAPPER_SCRIPT",
            tmp_path / "missing-source-wrapper.sh",
        )

        assert update_privilege._sudo_prefix() == ["sudo", "-n", os.fspath(wrapper)]

    def test_sudo_prefix_uses_packaged_install_layout(self, monkeypatch, tmp_path) -> None:
        repo_root = tmp_path / "repo"
        wrapper = repo_root / "apps" / "server" / "scripts" / "vibesensor_update_sudo.sh"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("#!/usr/bin/env bash\n")
        wrapper.chmod(0o755)

        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        monkeypatch.delenv("VIBESENSOR_UPDATE_SUDO_WRAPPER", raising=False)
        monkeypatch.delenv("VIBESENSOR_REPO_PATH", raising=False)
        monkeypatch.setattr(update_privilege, "_DEFAULT_INSTALL_REPO", repo_root)
        monkeypatch.setattr(
            update_privilege,
            "_SOURCE_TREE_WRAPPER_SCRIPT",
            tmp_path / "missing-source-wrapper.sh",
        )

        assert update_privilege._sudo_prefix() == ["sudo", "-n", os.fspath(wrapper)]
