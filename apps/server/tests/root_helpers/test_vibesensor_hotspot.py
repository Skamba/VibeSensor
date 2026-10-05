"""Root-side hotspot helper: settings for hotspot_nmcli.sh and the periodic watchdog."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from test_support.root_helpers import ROOT_HELPERS_DIR, load_root_helper

from vibesensor.app.config_defaults import DEFAULT_CONFIG
from vibesensor.hotspot.captive_portal import CAPTIVE_PROBE_HOSTS, HOTSPOT_ADDRESS
from vibesensor.hotspot.constants import HOTSPOT_CON_NAME, HOTSPOT_IFNAME, HOTSPOT_IP
from vibesensor.updates.wifi.wifi_uplink_setup import psk_passwd_file

hotspot = load_root_helper("vibesensor_hotspot.py")

_ACTIVE = ("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active")
_UP = ("nmcli", "--wait", "15", "connection", "up", HOTSPOT_CON_NAME)
_REPROVISION = ("systemctl", "restart", "--no-block", "vibesensor-hotspot.service")


def test_fixed_settings_match_the_server_package() -> None:
    ap_defaults = DEFAULT_CONFIG["ap"]
    assert isinstance(ap_defaults, dict)

    assert (hotspot.DEFAULT_SSID, hotspot.DEFAULT_PSK) == (ap_defaults["ssid"], ap_defaults["psk"])
    assert hotspot.HOTSPOT_IP == HOTSPOT_IP
    assert hotspot.HOTSPOT_IFNAME == HOTSPOT_IFNAME
    assert hotspot.HOTSPOT_CON_NAME == HOTSPOT_CON_NAME
    assert hotspot.CAPTIVE_PROBE_HOSTS == CAPTIVE_PROBE_HOSTS


def _exports(config_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[list[str], str]:
    assert hotspot.main(["config", str(config_path)]) == 0
    captured = capsys.readouterr()
    return captured.out.splitlines(), captured.err


def test_config_exports_operator_credentials_and_fixed_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.yaml"
    # Older device configs may still carry removed keys such as ap.channel.
    config_path.write_text("ap:\n  ssid: Workshop\n  psk: secret-psk\n  channel: 11\n")

    lines, err = _exports(config_path, capsys)

    assert err == ""
    assert lines == [
        "SSID=Workshop",
        "PSK=secret-psk",
        "IP=10.4.0.1/24",
        "CHANNEL=7",
        "IFNAME=wlan0",
        "CON_NAME=VibeSensor-AP",
        f"CAPTIVE_DNS_ADDRESS=/{'/'.join(CAPTIVE_PROBE_HOSTS)}/{HOTSPOT_ADDRESS}",
    ]


@pytest.mark.parametrize(
    ("config_text", "expected_warning"),
    [
        pytest.param("ap: [unterminated\n", "Failed to parse hotspot config", id="parse-error"),
        pytest.param("- item\n", "must contain a top-level mapping", id="top-level-list"),
        pytest.param("ap: disabled\n", "has a non-mapping 'ap' section", id="ap-not-mapping"),
    ],
)
def test_config_warns_and_falls_back_to_defaults_on_invalid_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], config_text: str, expected_warning: str
) -> None:
    defaults, defaults_err = _exports(tmp_path / "missing.yaml", capsys)
    broken_path = tmp_path / "broken.yaml"
    broken_path.write_text(config_text)

    broken, broken_err = _exports(broken_path, capsys)

    assert defaults_err == ""
    assert defaults[:2] == ["SSID=VibeSensor", "PSK=''"]
    assert broken == defaults
    assert "WARNING: " in broken_err and str(broken_path) in broken_err
    assert expected_warning in broken_err and "using defaults" in broken_err


def test_hotspot_script_evals_exports_as_literal_values(tmp_path: Path) -> None:
    """hotspot_nmcli.sh runs as root and evals the exports; SSID/PSK must stay data."""

    marker = tmp_path / "pwned"
    ssid = f'it\'s $(touch {marker}) `id` "x"'
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"ap:\n  ssid: '{ssid.replace(chr(39), chr(39) * 2)}'\n  psk: a b\n")
    exports = subprocess.run(
        [sys.executable, "-I", ROOT_HELPERS_DIR / "vibesensor_hotspot.py", "config", config_path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    shell = subprocess.run(
        ["bash", "-c", 'eval "$1"; printf "%s\\n%s\\n" "$SSID" "$PSK"', "bash", exports],
        capture_output=True,
        text=True,
        check=True,
    )

    assert shell.stdout.splitlines() == [ssid, "a b"]
    assert not marker.exists()


class FakeSystem:
    """Answers commands from a script; each argv maps to a queue of (rc, stdout)."""

    def __init__(self, script: dict[tuple[str, ...], list[tuple[int, str]]]) -> None:
        self._script = script
        self.calls: list[tuple[str, ...]] = []
        self.sleeps: list[float] = []

    def run(self, argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        key = tuple(argv)
        self.calls.append(key)
        queue = self._script[key]
        rc, stdout = queue.pop(0) if len(queue) > 1 else queue[0]
        return subprocess.CompletedProcess(list(argv), rc, stdout, "boom" if rc else "")

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def check(self) -> int:
        return hotspot.check_hotspot(self.run, self.sleep)


def test_active_hotspot_is_left_alone() -> None:
    fake = FakeSystem({_ACTIVE: [(0, f"{HOTSPOT_CON_NAME}:wlan0\nlo:lo\n")]})

    assert fake.check() == 0
    assert fake.calls == [_ACTIVE]


def test_interface_owned_by_update_uplink_is_left_alone() -> None:
    fake = FakeSystem({_ACTIVE: [(0, "VibeSensor-Uplink:wlan0\n")]})

    assert fake.check() == 0
    assert fake.calls == [_ACTIVE]


def test_inactive_hotspot_is_brought_up_after_backoff() -> None:
    fake = FakeSystem({_ACTIVE: [(0, "eth0-wired:eth0\n")], _UP: [(10, ""), (0, "")]})

    assert fake.check() == 0
    assert fake.calls == [_ACTIVE, _UP, _UP]
    assert fake.sleeps == [hotspot.RETRY_DELAYS_S[1]]


def test_persistent_up_failure_reprovisions_the_hotspot() -> None:
    fake = FakeSystem({_ACTIVE: [(0, "")], _UP: [(10, "")], _REPROVISION: [(0, "")]})

    assert fake.check() == 1
    assert fake.calls == [_ACTIVE, *[_UP] * len(hotspot.RETRY_DELAYS_S), _REPROVISION]
    assert fake.sleeps == [delay for delay in hotspot.RETRY_DELAYS_S if delay]


@pytest.mark.parametrize(("restart_rc", "expected"), [(0, 1), (1, 2)])
def test_unresponsive_networkmanager_reprovisions(restart_rc: int, expected: int) -> None:
    fake = FakeSystem({_ACTIVE: [(8, "")], _REPROVISION: [(restart_rc, "")]})

    assert fake.check() == expected
    assert fake.calls == [_ACTIVE, _REPROVISION]


@pytest.mark.parametrize("psk", ["secret-psk", " lead\\trail ", "tab\there"])
def test_passwd_file_matches_the_updater_uplink_encoding(
    psk: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"ap": {"psk": psk}}))

    assert hotspot.main(["passwd-file", str(config_path)]) == 0
    assert capsys.readouterr().out == psk_passwd_file(psk)


def test_open_hotspot_prints_an_empty_passwd_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("ap:\n  ssid: Open Shop\n")

    assert hotspot.main(["passwd-file", str(config_path)]) == 0
    assert capsys.readouterr().out == ""


def test_run_command_reports_missing_binary_as_failure() -> None:
    assert hotspot.run_command(["/nonexistent/vibesensor-binary"], 1).returncode == 127


@pytest.mark.parametrize(
    "argv",
    [[], ["status"], ["watchdog", "--mode"], ["config", "a", "b"], ["passwd-file", "a", "b"]],
)
def test_unknown_invocations_are_refused(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert hotspot.main(argv) == 2
    assert "Usage:" in capsys.readouterr().err
