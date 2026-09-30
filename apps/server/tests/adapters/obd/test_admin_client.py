from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from vibesensor.adapters.obd import admin_client as admin_client_module
from vibesensor.adapters.obd.admin_client import CommandResult, ObdAdminClient
from vibesensor.shared.operational_errors import ExternalCommandError


def test_scan_devices_invokes_sudo_helper_and_parses_json(tmp_path: Path) -> None:
    helper_script = tmp_path / "vibesensor_obd_admin.py"
    calls: list[tuple[list[str], int]] = []

    def runner(argv: list[str], timeout_s: int) -> CommandResult:
        calls.append((argv, timeout_s))
        return CommandResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "devices": [
                        {
                            "mac_address": "02000000004d",
                            "name": "OBDLink MX+",
                            "paired": True,
                            "trusted": True,
                            "connected": False,
                            "rfcomm_channel": 1,
                        }
                    ]
                }
            ),
            stderr="",
        )

    client = ObdAdminClient(helper_script=helper_script, runner=runner)

    devices = client.scan_devices(timeout_s=9)

    assert calls == [(["sudo", "-n", str(helper_script), "scan", "--timeout", "9"], 17)]
    assert devices[0].mac_address == "02000000004d"
    assert devices[0].name == "OBDLink MX+"
    assert devices[0].rfcomm_channel == 1


def test_pair_device_raises_operational_error_from_helper_json(tmp_path: Path) -> None:
    helper_script = tmp_path / "vibesensor_obd_admin.py"

    def runner(argv: list[str], timeout_s: int) -> CommandResult:
        del argv, timeout_s
        return CommandResult(
            returncode=1,
            stdout=json.dumps({"error": "Bluetooth OBD pairing failed"}),
            stderr="",
        )

    client = ObdAdminClient(helper_script=helper_script, runner=runner)

    with pytest.raises(ExternalCommandError, match="Bluetooth OBD pairing failed"):
        client.pair_device("02000000004d")


def test_scan_devices_reports_noninteractive_sudo_failure_cleanly(tmp_path: Path) -> None:
    helper_script = tmp_path / "vibesensor_obd_admin.py"

    def runner(argv: list[str], timeout_s: int) -> CommandResult:
        del argv, timeout_s
        return CommandResult(
            returncode=1,
            stdout="",
            stderr="sudo: a password is required",
        )

    client = ObdAdminClient(helper_script=helper_script, runner=runner)

    with pytest.raises(
        ExternalCommandError,
        match="Bluetooth OBD scan requires the Pi sudo helper and NOPASSWD sudoers entry",
    ):
        client.scan_devices()


def test_scan_devices_still_reports_invalid_json_when_stdout_is_malformed(tmp_path: Path) -> None:
    helper_script = tmp_path / "vibesensor_obd_admin.py"

    def runner(argv: list[str], timeout_s: int) -> CommandResult:
        del argv, timeout_s
        return CommandResult(
            returncode=0,
            stdout="sudo: a password is required",
            stderr="",
        )

    client = ObdAdminClient(helper_script=helper_script, runner=runner)

    with pytest.raises(ExternalCommandError, match="Bluetooth OBD helper returned invalid JSON"):
        client.scan_devices()


def test_default_helper_script_walks_up_to_repo_scripts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_file = (
        tmp_path
        / ".venv"
        / "lib"
        / "python3.13"
        / "site-packages"
        / "vibesensor"
        / "adapters"
        / "obd"
        / "admin_client.py"
    )
    package_file.parent.mkdir(parents=True)
    # Load a copy of the module from an installed-package-like location instead of
    # monkeypatching the real module's ``__file__``: coverage.py prefers a frame's
    # ``__file__`` global, so patching it misattributes the real module's lines.
    package_file.write_text(
        Path(admin_client_module.__file__).read_text(encoding="utf-8"), encoding="utf-8"
    )
    spec = importlib.util.spec_from_file_location("_installed_admin_client", package_file)
    assert spec is not None and spec.loader is not None
    installed_module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, installed_module)
    spec.loader.exec_module(installed_module)

    helper_script = tmp_path / "scripts" / "vibesensor_obd_admin.py"
    helper_script.parent.mkdir(parents=True)
    helper_script.write_text("", encoding="utf-8")

    assert installed_module._default_helper_script() == helper_script
