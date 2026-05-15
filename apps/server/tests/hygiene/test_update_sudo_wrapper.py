"""Guard the updater sudo wrapper install and allowlist behavior."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests._paths import REPO_ROOT, SERVER_ROOT

_WRAPPER = SERVER_ROOT / "scripts" / "vibesensor_update_sudo.sh"


def _write_tool(bin_dir: Path, name: str) -> Path:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$0 $*\"\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _run_wrapper(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("nmcli", "python3", "systemctl", "systemd-run"):
        _write_tool(bin_dir, name)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", os.fspath(_WRAPPER), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_update_sudo_wrapper_allows_expected_update_commands(tmp_path: Path) -> None:
    allowed_commands = [
        ["python3", "-c", "pass"],
        ["nmcli", "connection", "up", "VibeSensor-uplink"],
        ["nmcli", "--wait", "45", "device", "up", "usb0"],
        ["systemctl", "restart", "vibesensor.service"],
        [
            "systemd-run",
            "--unit",
            "vibesensor-post-update-restart",
            "--on-active=2s",
            "systemctl",
            "restart",
            "vibesensor.service",
        ],
    ]

    for command in allowed_commands:
        result = _run_wrapper(tmp_path, command)
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert result.stdout.strip().endswith(" ".join(command[1:]))


def test_update_sudo_wrapper_rejects_basename_spoofing(tmp_path: Path) -> None:
    evil_dir = tmp_path / "evil"
    evil_dir.mkdir()
    evil_nmcli = _write_tool(evil_dir, "nmcli")

    result = _run_wrapper(tmp_path, [os.fspath(evil_nmcli), "connection", "up", "x"])

    assert result.returncode == 126
    assert "is not allowed" in result.stderr
    assert result.stdout == ""


def test_update_sudo_wrapper_rejects_unexpected_subcommands(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, ["nmcli", "general", "status"])

    assert result.returncode == 126
    assert "is not allowed" in result.stderr
    assert result.stdout == ""


def test_update_sudo_wrapper_rejects_malformed_nmcli_options(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, ["nmcli", "--wait"])

    assert result.returncode == 126
    assert "is not allowed" in result.stderr
    assert result.stdout == ""


def test_manual_pi_install_installs_update_sudoers_entry() -> None:
    install_pi = (SERVER_ROOT / "scripts" / "install_pi.sh").read_text(encoding="utf-8")

    assert 'UPDATE_SUDO_WRAPPER="${PI_DIR}/scripts/vibesensor_update_sudo.sh"' in install_pi
    assert 'UPDATE_SUDOERS="/etc/sudoers.d/vibesensor-update"' in install_pi
    assert 'if [ ! -f "${UPDATE_SUDO_WRAPPER}" ]; then' in install_pi
    assert "${SERVICE_USER} ALL=(root) NOPASSWD: ${UPDATE_SUDO_WRAPPER}" in install_pi
    assert 'run_as_root install -o root -g root -m 0440 /dev/null "${UPDATE_SUDOERS}"' in install_pi
    assert 'run_as_root chmod 0440 "${UPDATE_SUDOERS}"' in install_pi


def test_pi_image_validation_requires_update_sudo_wrapper() -> None:
    validation = (
        REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "image_validation.sh"
    ).read_text(encoding="utf-8")

    assert "/opt/VibeSensor/apps/server/scripts/vibesensor_update_sudo.sh" in validation
    assert "update sudo wrapper entry missing" in validation
