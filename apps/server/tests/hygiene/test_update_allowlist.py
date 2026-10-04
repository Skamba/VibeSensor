"""Guard the updater allowlist wrapper that the privileged helper runs as root."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests._paths import SERVER_ROOT

_WRAPPER = SERVER_ROOT / "scripts" / "vibesensor_update_allowlist.sh"


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


def test_update_allowlist_allows_expected_update_commands(tmp_path: Path) -> None:
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


def test_update_allowlist_rejects_basename_spoofing(tmp_path: Path) -> None:
    evil_dir = tmp_path / "evil"
    evil_dir.mkdir()
    evil_nmcli = _write_tool(evil_dir, "nmcli")

    result = _run_wrapper(tmp_path, [os.fspath(evil_nmcli), "connection", "up", "x"])

    assert result.returncode == 126
    assert "is not allowed" in result.stderr
    assert result.stdout == ""


def test_update_allowlist_rejects_unexpected_subcommands(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, ["nmcli", "general", "status"])

    assert result.returncode == 126
    assert "is not allowed" in result.stderr
    assert result.stdout == ""


def test_update_allowlist_rejects_malformed_nmcli_options(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, ["nmcli", "--wait"])

    assert result.returncode == 126
    assert "is not allowed" in result.stderr
    assert result.stdout == ""


def test_update_allowlist_rejects_commands_outside_the_allowlist(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, ["bash", "-c", "id"])

    assert result.returncode == 126
    assert "is not allowed" in result.stderr
    assert result.stdout == ""
