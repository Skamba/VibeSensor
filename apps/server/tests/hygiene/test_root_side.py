"""The root-side manifest: release digest, installer stamp, and the server's check."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from _paths import REPO_ROOT, SERVER_ROOT

from vibesensor.common.root_side import (
    ROOT_SIDE_DIGEST,
    inspect_root_side,
    root_side_manifest,
)

_INSTALLER = SERVER_ROOT / "scripts" / "install_systemd_units.sh"
_IMAGE_VALIDATION = REPO_ROOT / "infra/pi-image/pi-gen/lib/image_validation.sh"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_release_digest_matches_the_root_side_tree() -> None:
    actual = _digest(root_side_manifest(SERVER_ROOT))

    assert actual == ROOT_SIDE_DIGEST, (
        "root-helpers/, scripts/ or systemd/ changed: set ROOT_SIDE_DIGEST in "
        f"vibesensor/common/root_side.py to {actual!r}. Devices need the root side "
        "reinstalled for this release (docs/operational-runbooks.md)."
    )


def test_manifest_matches_the_shell_pipeline_the_installer_and_operators_use() -> None:
    shell = subprocess.run(
        [
            "bash",
            "-c",
            "find root-helpers scripts systemd -maxdepth 1 -type f -exec sha256sum {} + "
            "| LC_ALL=C sort",
        ],
        cwd=SERVER_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert shell.stdout == root_side_manifest(SERVER_ROOT)


@pytest.mark.parametrize(
    ("unit", "stamp_text", "state"),
    [
        pytest.param(False, None, "not_installed", id="dev-or-docker"),
        pytest.param(True, None, "outdated", id="stamp-missing"),
        pytest.param(True, "old manifest\n", "outdated", id="other-release"),
    ],
)
def test_inspect_root_side_states(
    tmp_path: Path, unit: bool, stamp_text: str | None, state: str
) -> None:
    server_unit = tmp_path / "vibesensor.service"
    stamp = tmp_path / "root-side.sha256"
    if unit:
        server_unit.touch()
    if stamp_text is not None:
        stamp.write_text(stamp_text)

    status = inspect_root_side(server_unit=server_unit, stamp=stamp)

    assert status.state == state
    assert status.expected_digest == ROOT_SIDE_DIGEST
    assert status.installed_digest == (None if stamp_text is None else _digest(stamp_text))


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def test_installer_stamps_the_manifest_the_server_checks(tmp_path: Path) -> None:
    """Run install_systemd_units.sh against a sandbox and check what it installs and stamps.

    The copy only points /usr/local/lib/vibesensor, /etc/systemd/system, the
    journald drop-in, and the sudoers entry at the sandbox; id, systemctl, and
    install's root ownership are stubbed.
    """

    helper_dir = tmp_path / "usr-local-lib-vibesensor"
    unit_dir = tmp_path / "etc-systemd-system"
    unit_dir.mkdir()
    journald_dropin = tmp_path / "etc-systemd-journald.conf.d/90-vibesensor.conf"
    server = tmp_path / "apps/server"
    for dirname in ("root-helpers", "systemd"):
        (server / dirname).mkdir(parents=True)
        for source in (SERVER_ROOT / dirname).iterdir():
            if source.is_file():
                (server / dirname / source.name).write_bytes(source.read_bytes())
    (server / "scripts").mkdir()
    for source in (SERVER_ROOT / "scripts").iterdir():
        if source.is_file() and source != _INSTALLER:
            (server / "scripts" / source.name).write_bytes(source.read_bytes())
    installer = _INSTALLER.read_text()
    for real, sandboxed in (
        ("/usr/local/lib/vibesensor", str(helper_dir)),
        ("UNIT_DIR=/etc/systemd/system", f"UNIT_DIR={unit_dir}"),
        ("/etc/systemd/journald.conf.d/90-vibesensor.conf", str(journald_dropin)),
        ("UDEV_RULES_DIR=/etc/udev/rules.d", f"UDEV_RULES_DIR={tmp_path / 'udev'}"),
        ("/etc/sudoers.d/vibesensor-update", str(tmp_path / "sudoers-vibesensor-update")),
    ):
        assert real in installer, f"install_systemd_units.sh no longer uses {real}"
        installer = installer.replace(real, sandboxed)
    _write_executable(server / "scripts" / _INSTALLER.name, installer)
    # Stale copies an older install left in scripts/, and a symlink the
    # installer must neither install nor hash.
    (server / "scripts" / "vibesensor_update_sudo.sh").write_text("old\n")
    (server / "root-helpers" / "linked.py").symlink_to(tmp_path / "elsewhere.py")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _write_executable(stubs / "id", "#!/bin/sh\necho 0\n")
    _write_executable(stubs / "systemctl", "#!/bin/sh\nexit 0\n")
    _write_executable(
        stubs / "install",
        '#!/usr/bin/env bash\nargs=()\nwhile [ $# -gt 0 ]; do\n  case "$1" in\n'
        "    -o|-g) shift 2 ;;\n"
        '    *) args+=("$1"); shift ;;\n  esac\ndone\nexec /usr/bin/install "${args[@]}"\n',
    )

    result = subprocess.run(
        ["bash", str(server / "scripts" / _INSTALLER.name), "pi"],
        env={
            "PATH": f"{stubs}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "VIBESENSOR_SKIP_SERVICE_START": "1",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (server / "scripts" / "vibesensor_update_sudo.sh").exists()
    assert sorted(p.name for p in helper_dir.iterdir()) == sorted(
        [p.name for p in (SERVER_ROOT / "root-helpers").iterdir() if p.is_file()]
        + ["root-side.sha256"]
    )
    assert "__SERVICE_USER__" not in (unit_dir / "vibesensor.service").read_text()
    # The journal outlives a power cut.
    assert "\nStorage=persistent\n" in journald_dropin.read_text()
    assert (tmp_path / "udev/61-vibesensor-gps.rules").read_bytes() == (
        SERVER_ROOT / "systemd/61-vibesensor-gps.rules"
    ).read_bytes()
    # The stamp is the manifest of the tree the installer ran from (its own
    # sandboxed copy included), so on a device its digest is ROOT_SIDE_DIGEST.
    stamp = helper_dir / "root-side.sha256"
    assert stamp.read_text() == root_side_manifest(server)
    assert "root-helpers/linked.py" not in stamp.read_text()
    assert stamp.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize(
    ("stamp_text", "message"),
    [
        pytest.param("release", "", id="matching"),
        pytest.param(None, "root-side.sha256 (install_systemd_units.sh did not finish)", id="none"),
        pytest.param("old manifest\n", "does not match the app's ROOT_SIDE_DIGEST", id="stale"),
    ],
)
def test_image_validation_requires_the_stamp_the_app_expects(
    tmp_path: Path, stamp_text: str | None, message: str
) -> None:
    site_packages = tmp_path / "opt/VibeSensor/apps/server/.venv/lib/python3.13/site-packages"
    module = site_packages / "vibesensor/common/root_side.py"
    module.parent.mkdir(parents=True)
    module.write_text((SERVER_ROOT / "vibesensor/common/root_side.py").read_text())
    helper_dir = tmp_path / "usr/local/lib/vibesensor"
    helper_dir.mkdir(parents=True)
    if stamp_text is not None:
        text = root_side_manifest(SERVER_ROOT) if stamp_text == "release" else stamp_text
        (helper_dir / "root-side.sha256").write_text(text)

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'set -euo pipefail; source "{_IMAGE_VALIDATION}"; '
            f'assert_root_side_stamp_matches_app "{tmp_path}"',
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == (0 if stamp_text == "release" else 1), result.stdout
    assert message in result.stdout
