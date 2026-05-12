"""Deployment contracts for Pi image validation and systemd hardening."""

from __future__ import annotations

import shlex
import subprocess
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

import pytest
from _paths import REPO_ROOT

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
    assert shlex.split(_only_value(service, "AmbientCapabilities")) == ["CAP_NET_BIND_SERVICE"]
    assert shlex.split(_only_value(service, "CapabilityBoundingSet")) == ["CAP_NET_BIND_SERVICE"]

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
    (data_dir / "car_sources").mkdir()
    (data_dir / "report_i18n.json").write_text("{}", encoding="utf-8")
    (data_dir / "vehicle_configurations/example.json").write_text("{}", encoding="utf-8")
    (data_dir / "car_sources/example.json").write_text("{}", encoding="utf-8")

    result = _run_image_validation_script(f'assert_wheel_static_data_contract "{rootfs}"')
    assert result.returncode == 0

    (rootfs / "opt/VibeSensor/apps/server/vibesensor").mkdir()
    result = _run_image_validation_script(
        f'assert_wheel_static_data_contract "{rootfs}"',
        check=False,
    )

    assert result.returncode == 1
    assert "source tree still present" in result.stdout
