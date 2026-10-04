"""Deployment contracts for Pi image validation and systemd hardening."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from _paths import REPO_ROOT
from test_support.privileged_socket import HELPER_SCRIPT, serve_privileged_helper

from vibesensor.common.process_settings import DEFAULT_PRIVILEGED_SOCKET

_IMAGE_VALIDATION_SCRIPT = REPO_ROOT / "infra/pi-image/pi-gen/lib/image_validation.sh"
_SERVER_SERVICE = REPO_ROOT / "apps/server/systemd/vibesensor.service"


def _run_image_validation_script(
    command: str, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-lc",
            f'set -euo pipefail; source "{_IMAGE_VALIDATION_SCRIPT}"; {command}',
        ],
        check=check,
        capture_output=True,
        text=True,
    )


def _read_systemd_section(unit_path: Path, section_name: str) -> Mapping[str, list[str]]:
    section: str | None = None
    values: defaultdict[str, list[str]] = defaultdict(list)
    for raw_line in unit_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == section_name and "=" in line:
            key, value = line.split("=", 1)
            values[key].append(value)
    return values


def _only_value(section: Mapping[str, list[str]], key: str) -> str:
    values = section[key]
    assert len(values) == 1
    return values[0]


@pytest.mark.smoke
def test_server_systemd_runs_packaged_server_with_narrow_steady_state_privileges() -> None:
    service = _read_systemd_section(_SERVER_SERVICE, "Service")

    assert _only_value(service, "User") == "__SERVICE_USER__"
    assert _only_value(service, "PermissionsStartOnly") == "true"
    assert _only_value(service, "NoNewPrivileges") == "true"
    assert _only_value(service, "PrivateTmp") == "true"
    assert _only_value(service, "ProtectSystem") == "full"
    assert shlex.split(_only_value(service, "ExecStart")) == [
        "__VENV_DIR__/bin/vibesensor-server",
        "--config",
        "/etc/vibesensor/config.yaml",
    ]
    assert set(shlex.split(_only_value(service, "ReadWritePaths"))) == {
        "/var/lib/vibesensor",
        "/var/log/vibesensor",
        "__VENV_DIR__",
    }
    # Port 80 and stepping the RTC-less clock (vibesensor.clock); nothing else.
    expected_caps = ["CAP_NET_BIND_SERVICE", "CAP_SYS_TIME"]
    assert shlex.split(_only_value(service, "AmbientCapabilities")) == expected_caps
    assert shlex.split(_only_value(service, "CapabilityBoundingSet")) == expected_caps
    assert "CAP_SYS_ADMIN" not in _only_value(service, "CapabilityBoundingSet")

    prestart_commands = [shlex.split(value) for value in service["ExecStartPre"]]
    assert ["/usr/bin/test", "-r", "/etc/vibesensor/config.yaml"] in prestart_commands
    assert [
        "/usr/bin/chown",
        "-R",
        "__SERVICE_USER__:__SERVICE_USER__",
        "/var/log/vibesensor",
        "/var/lib/vibesensor",
    ] in prestart_commands
    for writable_path in ("/var/log/vibesensor", "/var/lib/vibesensor", "__VENV_DIR__"):
        assert ["/usr/bin/test", "-w", writable_path] in prestart_commands


@pytest.mark.smoke
def test_image_validation_accepts_wheel_static_data_and_rejects_source_tree(
    tmp_path: Path,
) -> None:
    rootfs = tmp_path / "rootfs"
    data_dir = (
        rootfs / "opt/VibeSensor/apps/server/.venv/lib/python3.13/site-packages/vibesensor/data"
    )
    (data_dir / "vehicle_configurations").mkdir(parents=True)
    (data_dir / "report_i18n.json").write_text("{}", encoding="utf-8")
    (data_dir / "vehicle_configurations/example.json").write_text("{}", encoding="utf-8")

    result = _run_image_validation_script(f'assert_wheel_static_data_contract "{rootfs}"')
    assert result.returncode == 0

    (rootfs / "opt/VibeSensor/apps/server/vibesensor").mkdir()
    result = _run_image_validation_script(
        f'assert_wheel_static_data_contract "{rootfs}"',
        check=False,
    )

    assert result.returncode == 1
    assert "source tree still present" in result.stdout
    assert "apps/server/vibesensor" in result.stdout


_SYSTEMD_DIR = REPO_ROOT / "apps/server/systemd"
_PRIVILEGED_SOCKET = _SYSTEMD_DIR / "vibesensor-privileged.socket"
_PRIVILEGED_SERVICE = _SYSTEMD_DIR / "vibesensor-privileged@.service"
_IMAGE_PLACEHOLDERS = {
    "__PI_DIR__": "/opt/VibeSensor/apps/server",
    "__VENV_DIR__": "/opt/VibeSensor/apps/server/.venv",
    "__SERVICE_USER__": "pi",
}


@pytest.mark.smoke
def test_privileged_helper_units_line_up_with_the_server_and_its_client() -> None:
    server_unit = _read_systemd_section(_SERVER_SERVICE, "Unit")
    server = _read_systemd_section(_SERVER_SERVICE, "Service")
    socket_unit = _read_systemd_section(_PRIVILEGED_SOCKET, "Socket")
    helper = _read_systemd_section(_PRIVILEGED_SERVICE, "Service")

    assert "vibesensor-privileged.socket" in server_unit["Wants"]
    assert "vibesensor-privileged.socket" in server_unit["After"]
    assert _only_value(socket_unit, "ListenStream") == str(DEFAULT_PRIVILEGED_SOCKET)
    assert _only_value(socket_unit, "SocketUser") == _only_value(server, "User")
    assert _only_value(socket_unit, "SocketMode") == "0600"
    assert _only_value(socket_unit, "Accept") == "yes"
    assert _read_systemd_section(_PRIVILEGED_SOCKET, "Install")["WantedBy"] == ["sockets.target"]

    exec_start = shlex.split(_only_value(helper, "ExecStart"))
    assert exec_start[:2] == ["/usr/bin/python3", "-I"]
    assert exec_start[2:] == ["__PI_DIR__/scripts/vibesensor_privileged_helper.py"]
    assert HELPER_SCRIPT.is_file()
    assert _only_value(helper, "StandardInput") == "socket"
    assert _only_value(helper, "StandardOutput") == "socket"
    assert "User" not in helper  # each request instance runs as root


_PRIVILEGED_PATHS_UNDER_SERVICE_RESTRICTIONS = """
import asyncio
from pathlib import Path

from vibesensor.common.privileged_helper import PrivilegedResult
from vibesensor.speed.obd.admin_client import _default_runner as obd_runner
from vibesensor.updates.runner import CommandRunner

assert "NoNewPrivs:\\t1" in Path("/proc/self/status").read_text()
update = asyncio.run(CommandRunner().run(["python3", "-c", "pass"], timeout=10, privileged=True))
assert update == (0, "", ""), update
assert isinstance(obd_runner(["--help"], 20), PrivilegedResult)
print("ok")
"""


@pytest.mark.smoke
@pytest.mark.skipif(shutil.which("setpriv") is None, reason="needs util-linux setpriv")
def test_privileged_commands_work_under_the_server_unit_restrictions() -> None:
    """Regression guard: sudo silently broke because the unit sets NoNewPrivileges.

    Runs the updater and Bluetooth OBD privileged paths with the server unit's
    NoNewPrivileges setting applied, against the real root-side helper script.
    Any setuid-based mechanism (sudo, pkexec, su) fails here.
    """

    server = _read_systemd_section(_SERVER_SERVICE, "Service")
    restrictions = ["--no-new-privs"] if _only_value(server, "NoNewPrivileges") == "true" else []
    assert restrictions, "vibesensor.service dropped NoNewPrivileges; keep the unit hardened"

    with serve_privileged_helper() as socket_path:
        completed = subprocess.run(
            [
                "setpriv",
                *restrictions,
                sys.executable,
                "-c",
                _PRIVILEGED_PATHS_UNDER_SERVICE_RESTRICTIONS,
            ],
            env={**os.environ, "VIBESENSOR_PRIVILEGED_SOCKET": str(socket_path)},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def _render_image_rootfs(rootfs: Path) -> None:
    unit_dir = rootfs / "etc/systemd/system"
    (unit_dir / "sockets.target.wants").mkdir(parents=True)
    for unit in ("vibesensor.service", _PRIVILEGED_SOCKET.name, _PRIVILEGED_SERVICE.name):
        text = (_SYSTEMD_DIR / unit).read_text(encoding="utf-8")
        for placeholder, value in _IMAGE_PLACEHOLDERS.items():
            text = text.replace(placeholder, value)
        (unit_dir / unit).write_text(text, encoding="utf-8")
    (unit_dir / "sockets.target.wants" / _PRIVILEGED_SOCKET.name).symlink_to(
        f"/etc/systemd/system/{_PRIVILEGED_SOCKET.name}"
    )
    scripts_dir = rootfs / "opt/VibeSensor/apps/server/scripts"
    scripts_dir.mkdir(parents=True)
    for script in (
        "vibesensor_privileged_helper.py",
        "vibesensor_update_allowlist.sh",
        "vibesensor_obd_admin.py",
    ):
        shutil.copy2(HELPER_SCRIPT.parent / script, scripts_dir / script)


def _break_with_sudoers(rootfs: Path) -> None:
    (rootfs / "etc/sudoers.d").mkdir(parents=True)
    (rootfs / "etc/sudoers.d/vibesensor-update").write_text("pi ALL=(root) NOPASSWD: x\n")


def _drop_no_new_privileges(rootfs: Path) -> None:
    unit = rootfs / "etc/systemd/system/vibesensor.service"
    unit.write_text(unit.read_text().replace("NoNewPrivileges=true", "NoNewPrivileges=false"))


def _mismatch_socket_user(rootfs: Path) -> None:
    unit = rootfs / "etc/systemd/system/vibesensor-privileged.socket"
    unit.write_text(unit.read_text().replace("SocketUser=pi", "SocketUser=root"))


def _disable_socket(rootfs: Path) -> None:
    (rootfs / "etc/systemd/system/sockets.target.wants/vibesensor-privileged.socket").unlink()


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("breakage", "message"),
    [
        (None, ""),
        (_break_with_sudoers, "stale"),
        (_drop_no_new_privileges, "NoNewPrivileges=true"),
        (_mismatch_socket_user, "SocketUser does not match"),
        (_disable_socket, "not enabled in sockets.target"),
    ],
)
def test_image_validation_checks_the_privileged_helper_contract(
    tmp_path: Path, breakage: Callable[[Path], None] | None, message: str
) -> None:
    rootfs = tmp_path / "rootfs"
    _render_image_rootfs(rootfs)
    if breakage is not None:
        breakage(rootfs)

    result = _run_image_validation_script(
        f'assert_privileged_helper_contract "{rootfs}"', check=False
    )

    assert result.returncode == (0 if breakage is None else 1), result.stdout
    assert message in result.stdout
