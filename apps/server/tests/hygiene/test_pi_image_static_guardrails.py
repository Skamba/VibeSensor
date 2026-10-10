"""Deployment contracts for Pi image validation and systemd hardening."""

from __future__ import annotations

import os
import re
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
from test_support.root_helpers import ROOT_HELPERS_DIR

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
_CLOUD_INIT_OFF = "vibesensor-cloud-init-off.service"
_ROOT_HELPER_DIR = "/usr/local/lib/vibesensor"
_SYSTEM_BIN_DIRS = ("/usr/bin/", "/bin/", "/usr/sbin/", "/sbin/")
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
    assert exec_start == ["/usr/bin/python3", "-I", f"{_ROOT_HELPER_DIR}/{HELPER_SCRIPT.name}"]
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
    """Lay out units and root helpers the way install_systemd_units.sh does on the image."""

    unit_dir = rootfs / "etc/systemd/system"
    (unit_dir / "sockets.target.wants").mkdir(parents=True)
    (unit_dir / "cloud-init.target.wants").mkdir()
    for unit in _SYSTEMD_DIR.iterdir():
        text = unit.read_text(encoding="utf-8")
        for placeholder, value in _IMAGE_PLACEHOLDERS.items():
            text = text.replace(placeholder, value)
        (unit_dir / unit.name).write_text(text, encoding="utf-8")
    (unit_dir / "sockets.target.wants" / _PRIVILEGED_SOCKET.name).symlink_to(
        f"/etc/systemd/system/{_PRIVILEGED_SOCKET.name}"
    )
    (unit_dir / "cloud-init.target.wants" / _CLOUD_INIT_OFF).symlink_to(
        f"/etc/systemd/system/{_CLOUD_INIT_OFF}"
    )
    release_helpers = rootfs / "opt/VibeSensor/apps/server/root-helpers"
    installed_helpers = rootfs / _ROOT_HELPER_DIR.lstrip("/")
    for helpers_dir in (release_helpers, installed_helpers):
        helpers_dir.mkdir(parents=True)
        for helper in ROOT_HELPERS_DIR.iterdir():
            if helper.is_file():
                shutil.copy2(helper, helpers_dir / helper.name)
    (rootfs / "opt/VibeSensor/apps/server/.venv/bin").mkdir(parents=True)
    (rootfs / "usr/bin").mkdir(parents=True)
    (rootfs / "bin").symlink_to("usr/bin")
    for tool in ("python3.13", "dash", "test", "chown", "touch"):
        (rootfs / "usr/bin" / tool).write_text("#!/bin/true\n", encoding="utf-8")
    (rootfs / "usr/bin/python3").symlink_to("python3.13")
    (rootfs / "usr/bin/sh").symlink_to("dash")
    for path in [rootfs, *rootfs.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o755)


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


def _server_waits_for_network_online(rootfs: Path) -> None:
    unit = rootfs / "etc/systemd/system/vibesensor.service"
    unit.write_text(unit.read_text().replace("[Unit]\n", "[Unit]\nAfter=network-online.target\n"))


def _cloud_init_disabled_in_image(rootfs: Path) -> None:
    (rootfs / "etc/cloud").mkdir(parents=True)
    (rootfs / "etc/cloud/cloud-init.disabled").touch()


def _cloud_init_off_not_enabled(rootfs: Path) -> None:
    (rootfs / "etc/systemd/system/cloud-init.target.wants" / _CLOUD_INIT_OFF).unlink()


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("breakage", "message"),
    [
        (None, ""),
        (_server_waits_for_network_online, "must not wait for network-online.target"),
        (_cloud_init_disabled_in_image, "cloud-init must provision the first boot"),
        (_cloud_init_off_not_enabled, "not enabled in cloud-init.target"),
    ],
)
def test_image_validation_checks_the_fast_boot_contract(
    tmp_path: Path, breakage: Callable[[Path], None] | None, message: str
) -> None:
    """Cold boot: the server starts beside the hotspot, cloud-init runs on first boot only."""

    rootfs = tmp_path / "rootfs"
    _render_image_rootfs(rootfs)
    if breakage is not None:
        breakage(rootfs)

    result = _run_image_validation_script(f'assert_fast_boot_contract "{rootfs}"', check=False)

    assert result.returncode == (0 if breakage is None else 1), result.stdout
    assert message in result.stdout


def _root_run_commands(unit_path: Path) -> list[list[str]]:
    """Return the argv of every command systemd runs as root for *unit_path*."""

    service = _read_systemd_section(unit_path, "Service")
    user = service.get("User", ["root"])[-1]
    start_only = service.get("PermissionsStartOnly", ["false"])[-1] == "true"
    commands: list[list[str]] = []
    for key, values in service.items():
        if not key.startswith("Exec"):
            continue
        for value in values:
            command = value.lstrip("-@:+!")
            prefix = value[: len(value) - len(command)]
            runs_as_root = (
                user == "root"
                or "+" in prefix
                or "!" in prefix
                or (start_only and key != "ExecStart")
            )
            if runs_as_root:
                commands.append(shlex.split(command))
    return commands


def _executed_files(argv: list[str]) -> list[str]:
    """The program and, for an interpreter, the script it runs (inline ``-c`` code excluded)."""

    program = Path(argv[0]).name
    if program.startswith("python"):
        assert argv[1] == "-I", f"root runs Python without -I (isolated mode): {argv}"
        return [argv[0], argv[2]]
    if program in {"sh", "bash"} and argv[1] != "-c":
        return [argv[0], argv[1]]
    return [argv[0]]


@pytest.mark.smoke
def test_root_units_execute_only_the_root_owned_helper_copies() -> None:
    """Root must never run code the service user can change (its venv, the install tree)."""

    root_commands = {
        unit.name: _root_run_commands(unit) for unit in sorted(_SYSTEMD_DIR.glob("*.service"))
    }
    executed = {
        path
        for commands in root_commands.values()
        for argv in commands
        for path in _executed_files(argv)
    }

    assert root_commands["vibesensor-hotspot-self-heal.service"] == [
        ["/usr/bin/python3", "-I", f"{_ROOT_HELPER_DIR}/vibesensor_hotspot.py", "watchdog"]
    ]
    for path in executed:
        assert "__PI_DIR__" not in path and "__VENV_DIR__" not in path, path
        assert path.startswith((*_SYSTEM_BIN_DIRS, f"{_ROOT_HELPER_DIR}/")), path
        if path.startswith(f"{_ROOT_HELPER_DIR}/"):
            assert (ROOT_HELPERS_DIR / Path(path).name).is_file(), path
    for commands in root_commands.values():
        for argv in commands:
            if argv[:2] in (["/bin/sh", "-c"], ["/bin/bash", "-c"]):
                assert "__PI_DIR__" not in argv[2] and "__VENV_DIR__" not in argv[2], argv


_IMPORT_AUDIT = """
import runpy, sys, sysconfig, tempfile
from pathlib import Path

namespace = runpy.run_path(sys.argv[1], run_name="root_helper_audit")
if "print_exports" in namespace:  # hotspot helper: also take the lazy YAML import path
    config = Path(tempfile.mkdtemp()) / "config.yaml"
    config.write_text("ap:\\n  ssid: Test\\n")
    namespace["print_exports"](config)
stdlib = {Path(sysconfig.get_paths()[key]).resolve() for key in ("stdlib", "platstdlib")}
for name, module in list(sys.modules.items()):
    origin = getattr(module, "__file__", None)
    if origin and not any(root in Path(origin).resolve().parents for root in stdlib):
        print(f"non-stdlib module {name} from {origin}", file=sys.stderr)
        raise SystemExit(1)
"""


@pytest.mark.smoke
@pytest.mark.parametrize(
    "helper", sorted(p.name for p in ROOT_HELPERS_DIR.iterdir() if p.suffix == ".py")
)
def test_root_helpers_load_only_the_standard_library(helper: str) -> None:
    """Root runs these with the system python3 -I: nothing from the venv may be imported."""

    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", _IMPORT_AUDIT, str(ROOT_HELPERS_DIR / helper)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    first_line = (ROOT_HELPERS_DIR / helper).read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/python3 -I"


@pytest.mark.smoke
@pytest.mark.parametrize("helper", sorted(p.name for p in ROOT_HELPERS_DIR.iterdir()))
def test_root_helpers_never_reach_into_the_service_users_tree(helper: str) -> None:
    text = (ROOT_HELPERS_DIR / helper).read_text(encoding="utf-8")

    for marker in (r"\.venv\b", r"site-packages", r"\b(?:from|import|-m)\s+vibesensor(?:\.|\s|$)"):
        assert re.search(marker, text, re.MULTILINE) is None, f"{helper} matches {marker!r}"


def _venv_self_heal(rootfs: Path) -> None:
    unit = rootfs / "etc/systemd/system/vibesensor-hotspot-self-heal.service"
    (rootfs / "opt/VibeSensor/apps/server/.venv/bin/vibesensor-hotspot-self-heal").touch()
    unit.write_text(
        unit.read_text().replace(
            f"/usr/bin/python3 -I {_ROOT_HELPER_DIR}/vibesensor_hotspot.py watchdog",
            "/opt/VibeSensor/apps/server/.venv/bin/vibesensor-hotspot-self-heal",
        )
    )


def _hotspot_from_install_tree(rootfs: Path) -> None:
    unit = rootfs / "etc/systemd/system/vibesensor-hotspot.service"
    unit.write_text(
        unit.read_text().replace(
            f"{_ROOT_HELPER_DIR}/hotspot_nmcli.sh",
            "/opt/VibeSensor/apps/server/root-helpers/hotspot_nmcli.sh",
        )
    )
    (rootfs / "opt").chmod(0o777)


def _writable_helper(rootfs: Path) -> None:
    (rootfs / _ROOT_HELPER_DIR.lstrip("/") / "vibesensor_obd_admin.py").chmod(0o775)


def _python_without_isolation(rootfs: Path) -> None:
    unit = rootfs / "etc/systemd/system/vibesensor-privileged@.service"
    unit.write_text(unit.read_text().replace("/usr/bin/python3 -I ", "/usr/bin/python3 "))


def _stale_helper_copy(rootfs: Path) -> None:
    (rootfs / _ROOT_HELPER_DIR.lstrip("/") / "hotspot_nmcli.sh").write_text("#!/bin/sh\n")


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("breakage", "message"),
    [
        (None, ""),
        (_venv_self_heal, "from the service user's venv"),
        (_hotspot_from_install_tree, "/opt is writable by a non-root user"),
        (_writable_helper, "vibesensor_obd_admin.py is writable by a non-root user"),
        (_python_without_isolation, "without -I"),
        (_stale_helper_copy, "is not an installed copy of root-helpers/hotspot_nmcli.sh"),
    ],
)
def test_image_validation_rejects_root_running_code_the_service_user_can_change(
    tmp_path: Path, breakage: Callable[[Path], None] | None, message: str
) -> None:
    rootfs = tmp_path / "rootfs"
    _render_image_rootfs(rootfs)
    if breakage is not None:
        breakage(rootfs)

    result = _run_image_validation_script(
        f'assert_root_executes_only_root_owned_code "{rootfs}"', check=False
    )

    assert result.returncode == (0 if breakage is None else 1), result.stdout + result.stderr
    assert message in result.stdout


_HEADLESS_BOOT_STEP = (
    REPO_ROOT / "infra/pi-image/pi-gen/templates/stage-vibesensor/01-headless-boot/00-run.sh"
)
# Raspberry Pi OS's stock config.txt (pi-gen stage1), trimmed to the lines that matter.
_STOCK_CONFIG_TXT = """\
camera_auto_detect=1
display_auto_detect=1
dtoverlay=vc4-kms-v3d
max_framebuffers=2
disable_fw_kms_setup=1
{arm_64bit}
[cm4]
otg_mode=1

[all]
"""


def _headless_boot_partition(tmp_path: Path, *, arm_64bit: bool) -> Path:
    """Run the image's headless-boot stage step on a stock config.txt; return the bootfs."""

    rootfs = tmp_path / "rootfs"
    boot = rootfs / "boot/firmware"
    boot.mkdir(parents=True)
    (boot / "config.txt").write_text(
        _STOCK_CONFIG_TXT.format(arm_64bit="arm_64bit=1" if arm_64bit else ""), encoding="utf-8"
    )
    for firmware in ("start_cd.elf", "fixup_cd.dat"):
        (boot / firmware).touch()
    subprocess.run(
        ["bash", str(_HEADLESS_BOOT_STEP)],
        env={**os.environ, "ROOTFS_DIR": str(rootfs)},
        check=True,
    )
    return boot


def _gpu_mem_only_for_pi4(boot: Path) -> None:
    config = boot / "config.txt"
    config.write_text(config.read_text().replace("[all]\n# VibeSensor", "[pi4]\n# VibeSensor"))


def _kms_driver_enabled(boot: Path) -> None:
    config = boot / "config.txt"
    config.write_text(config.read_text().replace("#dtoverlay=vc4-kms-v3d", "dtoverlay=vc4-kms-v3d"))


def _camera_auto_detect(boot: Path) -> None:
    config = boot / "config.txt"
    config.write_text(config.read_text().replace("camera_auto_detect=0", "camera_auto_detect=1"))


def _no_cut_down_gpu_firmware(boot: Path) -> None:
    (boot / "start_cd.elf").unlink()


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("breakage", "message"),
    [
        (None, ""),
        (_gpu_mem_only_for_pi4, "gpu_mem=16 for all boards"),
        (_kms_driver_enabled, "KMS display driver"),
        (_camera_auto_detect, "camera_auto_detect=1"),
        (_no_cut_down_gpu_firmware, "start_cd.elf"),
    ],
)
def test_image_is_headless_with_the_minimum_gpu_split(
    tmp_path: Path, breakage: Callable[[Path], None] | None, message: str
) -> None:
    boot = _headless_boot_partition(tmp_path, arm_64bit=False)
    if breakage is not None:
        breakage(boot)

    result = _run_image_validation_script(f'assert_headless_boot_config "{boot}"', check=False)

    assert result.returncode == (0 if breakage is None else 1), result.stdout
    assert message in result.stdout


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("libc_arch", "arm_64bit", "expected_arch", "message"),
    [
        ("armhf", False, "armhf", ""),
        ("arm64", True, "arm64", ""),
        ("armhf", False, "arm64", "userland is 'armhf' (libc6), expected 'arm64'"),
        ("arm64", False, "arm64", "arm_64bit=1"),
        ("armhf", True, "armhf", "must not set arm_64bit=1"),
    ],
)
def test_image_validation_checks_the_target_architecture(
    tmp_path: Path, libc_arch: str, arm_64bit: bool, expected_arch: str, message: str
) -> None:
    boot = _headless_boot_partition(tmp_path, arm_64bit=arm_64bit)
    rootfs = tmp_path / "rootfs"
    (rootfs / "var/lib/dpkg").mkdir(parents=True)
    (rootfs / "var/lib/dpkg/status").write_text(
        "Package: libc-bin\nArchitecture: all\n\n"
        f"Package: libc6\nStatus: install ok installed\nArchitecture: {libc_arch}\n\n",
        encoding="utf-8",
    )

    result = _run_image_validation_script(
        f'assert_image_architecture "{rootfs}" "{boot}" {expected_arch}', check=False
    )

    assert result.returncode == (0 if not message else 1), result.stdout
    assert message in result.stdout
