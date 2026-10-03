from __future__ import annotations

import os

import vibesensor.updates.privilege as update_privilege
from vibesensor.updates.runner import sanitize_log_line as sanitize_log_line


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
