"""hotspot_nmcli.sh end to end against stub nmcli/ip/systemctl.

The script runs as root on the Pi and writes to /var/log/wifi and
/etc/NetworkManager. The harness runs a copy whose only edits point those
paths and the system ``python3`` at a temporary sandbox. Every command it runs
(nmcli, ip, rfkill, iw, systemctl, ...) is a stub on ``PATH`` that records its
arguments, so the tests check the exact NetworkManager calls for each
provisioning path.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from test_support.root_helpers import ROOT_HELPERS_DIR

_CON = "VibeSensor-AP"
_DEFAULT_CONFIG = "ap:\n  ssid: Workshop\n  psk: secret-psk\n"
_PASSWD_FILE_UP = re.compile(rf"connection up {_CON} passwd-file /dev/fd/\d+")

# State lives in files under $STUB_STATE: "connections" (one profile name per
# line), "interfaces" (devices `ip link show` knows), "wifi_device" (what
# `nmcli device status` reports as wifi), and flag files that inject failures.
_NMCLI_STUB = r"""#!/usr/bin/env bash
s="${STUB_STATE}"
printf 'nmcli %s\n' "$*" >>"${s}/calls"
touch "${s}/connections"
has_con() { grep -Fxq -- "$1" "${s}/connections"; }
wifi="$(cat "${s}/wifi_device" 2>/dev/null || true)"
case "$*" in
  "-t -f RUNNING general")
    if [ -e "${s}/nm_not_ready" ]; then echo starting; else echo running; fi ;;
  "general status")
    [ -e "${s}/nm_not_ready" ] && exit 8
    echo "STATE CONNECTIVITY"; echo "connected none" ;;
  "-t -f DEVICE,TYPE device status")
    [ -n "${wifi}" ] && echo "${wifi}:wifi"
    echo "eth0:ethernet" ;;
  "-t -f DEVICE,TYPE,STATE,CONNECTION device status")
    [ -n "${wifi}" ] && echo "${wifi}:wifi:connected:${CON_NAME_HINT:-}"
    echo "eth0:ethernet:unavailable:" ;;
  "-t -f NAME connection show")
    cat "${s}/connections" ;;
  "connection show "*)
    has_con "${3}" || exit 10 ;;
  "connection delete "*)
    has_con "${3}" || exit 10
    grep -Fxv -- "${3}" "${s}/connections" >"${s}/connections.new" || true
    mv "${s}/connections.new" "${s}/connections" ;;
  "connection add "*)
    args=("$@")
    for i in "${!args[@]}"; do
      [ "${args[$i]}" = con-name ] && echo "${args[$((i + 1))]}" >>"${s}/connections"
    done ;;
  "connection modify "*)
    has_con "${3}" || exit 10
    [ -e "${s}/fail_modify" ] && exit 4
    exit 0 ;;
  "connection up "*)
    has_con "${3}" || exit 10
    [ -e "${s}/fail_up" ] && exit 4
    if [ "${4:-}" = passwd-file ]; then cat -- "${5}" >"${s}/passwd_file"; fi
    exit 0 ;;
  "-f GENERAL.STATE,IP4.ADDRESS connection show "*)
    has_con "${5}" || exit 10
    echo "GENERAL.STATE: activated"; echo "IP4.ADDRESS[1]: 10.4.0.1/24" ;;
esac
exit 0
"""
_IP_STUB = r"""#!/usr/bin/env bash
printf 'ip %s\n' "$*" >>"${STUB_STATE}/calls"
if [ "$1 $2" = "link show" ] && [ -n "${3:-}" ]; then
  grep -Fxq -- "$3" "${STUB_STATE}/interfaces" 2>/dev/null
fi
"""
_RECORDING_STUB = """#!/usr/bin/env bash
printf '%s %s\\n' "${0##*/}" "$*" >>"${STUB_STATE}/calls"
"""
_RECORDING_TOOLS = ("rfkill", "iw", "dmesg", "sysctl", "systemctl", "dnsmasq", "sleep")


@dataclass(frozen=True)
class HotspotRun:
    returncode: int
    calls: list[str]
    summary: dict[str, str]
    log_dir: Path
    nm_dir: Path
    passwd_file: str | None

    def nmcli_changes(self) -> list[str]:
        """The nmcli calls that change NetworkManager state, in order."""

        changing = ("connection add", "connection modify", "connection delete", "connection up")
        return [
            call.removeprefix("nmcli ")
            for call in self.calls
            if call.startswith("nmcli ")
            and (
                call.removeprefix("nmcli ").startswith(changing)
                or call in ("nmcli general reload", "nmcli radio wifi on")
            )
        ]

    def log_text(self) -> str:
        # The script logs through an awk process substitution that may still
        # be flushing when bash exits.
        log = self.log_dir / "hotspot.log"
        deadline = time.monotonic() + 5
        while "EXIT rc=" not in (text := log.read_text()) and time.monotonic() < deadline:
            time.sleep(0.05)
        return text


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def _sandboxed_script(tmp_path: Path) -> tuple[Path, Path, Path]:
    log_dir = tmp_path / "var-log-wifi"
    nm_dir = tmp_path / "etc-NetworkManager"
    lib = tmp_path / "lib"
    lib.mkdir()
    script = (ROOT_HELPERS_DIR / "hotspot_nmcli.sh").read_text()
    for real, sandboxed in (
        ("/var/log/wifi", str(log_dir)),
        ("/etc/NetworkManager", str(nm_dir)),
        ("/usr/bin/python3 -I", f"{sys.executable} -I"),
    ):
        assert real in script, f"hotspot_nmcli.sh no longer uses {real}; update the harness"
        script = script.replace(real, sandboxed)
    _write_executable(lib / "hotspot_nmcli.sh", script)
    (lib / "vibesensor_hotspot.py").write_text(
        (ROOT_HELPERS_DIR / "vibesensor_hotspot.py").read_text()
    )
    return lib / "hotspot_nmcli.sh", log_dir, nm_dir


def _run_hotspot(
    tmp_path: Path,
    *,
    config: str = _DEFAULT_CONFIG,
    connections: tuple[str, ...] = (),
    interfaces: tuple[str, ...] = ("wlan0",),
    wifi_device: str = "wlan0",
    flags: tuple[str, ...] = (),
) -> HotspotRun:
    script, log_dir, nm_dir = _sandboxed_script(tmp_path)
    state = tmp_path / "state"
    stubs = tmp_path / "bin"
    state.mkdir()
    stubs.mkdir()
    (state / "connections").write_text("".join(f"{name}\n" for name in connections))
    (state / "interfaces").write_text("".join(f"{name}\n" for name in interfaces))
    (state / "wifi_device").write_text(wifi_device)
    for flag in flags:
        (state / flag).touch()
    _write_executable(stubs / "nmcli", _NMCLI_STUB)
    _write_executable(stubs / "ip", _IP_STUB)
    _write_executable(stubs / "id", "#!/bin/sh\necho 0\n")
    for tool in _RECORDING_TOOLS:
        _write_executable(stubs / tool, _RECORDING_STUB)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config)

    completed = subprocess.run(
        ["bash", str(script), "--config", str(config_path)],
        env={"PATH": f"{stubs}{os.pathsep}/usr/bin{os.pathsep}/bin", "STUB_STATE": str(state)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    summary_file = log_dir / "summary.txt"
    summary = (
        dict(
            line.split("=", 1)
            for line in summary_file.read_text().splitlines()
            if "=" in line and not line.startswith(" ")
        )
        if summary_file.exists()
        else {}
    )
    return HotspotRun(
        returncode=completed.returncode,
        calls=(state / "calls").read_text().splitlines(),
        summary=summary,
        log_dir=log_dir,
        nm_dir=nm_dir,
        passwd_file=(
            (state / "passwd_file").read_text() if (state / "passwd_file").exists() else None
        ),
    )


_AP_SETTINGS = (
    f"connection modify {_CON} 802-11-wireless.mode ap 802-11-wireless.band bg "
    "802-11-wireless.channel 7 ipv4.method shared ipv4.addresses 10.4.0.1/24 "
    "ipv6.method ignore"
)


def test_first_boot_creates_the_wpa_hotspot_offline(tmp_path: Path) -> None:
    run = _run_hotspot(tmp_path)

    assert run.returncode == 0, run.log_text()
    *changes, up = run.nmcli_changes()
    assert changes == [
        "radio wifi on",
        "general reload",
        f"connection delete {_CON}",
        f"connection add type wifi ifname wlan0 con-name {_CON} autoconnect yes ssid Workshop",
        _AP_SETTINGS,
        f"connection modify {_CON} 802-11-wireless-security.key-mgmt wpa-psk",
    ]
    # The PSK reaches nmcli through a pipe, never on a command line.
    assert _PASSWD_FILE_UP.fullmatch(up)
    assert run.passwd_file == "802-11-wireless-security.psk:secret-psk\n"
    assert not any("secret-psk" in call for call in run.calls)
    assert "secret-psk" not in run.log_text()
    assert "systemctl disable --now dnsmasq.service" in run.calls
    assert run.summary["status"] == "OK"
    assert run.summary["ap_connection_exists"] == "yes"
    assert (run.summary["ssid"], run.summary["effective_ifname"]) == ("Workshop", "wlan0")
    assert (run.nm_dir / "conf.d/99-vibesensor-dnsmasq.conf").read_text() == (
        "[main]\ndns=dnsmasq\n"
    )
    captive = (run.nm_dir / "dnsmasq-shared.d/vibesensor-captive-portal.conf").read_text()
    assert captive.startswith("address=/connectivitycheck.gstatic.com/")
    assert captive.endswith("/10.4.0.1\n")
    assert (run.log_dir / "pre_nm_dev.txt").exists() and (run.log_dir / "post_meta.txt").exists()


def test_existing_wpa_profile_is_recreated_so_no_old_psk_survives(tmp_path: Path) -> None:
    run = _run_hotspot(tmp_path, connections=(_CON,))

    assert run.returncode == 0, run.log_text()
    changes = run.nmcli_changes()
    assert changes[2:4] == [
        f"connection delete {_CON}",
        f"connection add type wifi ifname wlan0 con-name {_CON} autoconnect yes ssid Workshop",
    ]
    assert _PASSWD_FILE_UP.fullmatch(changes[-1])
    assert run.passwd_file == "802-11-wireless-security.psk:secret-psk\n"


def test_open_hotspot_recreates_the_profile_without_security(tmp_path: Path) -> None:
    run = _run_hotspot(tmp_path, config="ap:\n  ssid: Open Shop\n", connections=(_CON,))

    assert run.returncode == 0, run.log_text()
    assert run.nmcli_changes()[2:] == [
        f"connection delete {_CON}",
        f"connection add type wifi ifname wlan0 con-name {_CON} autoconnect yes ssid Open Shop",
        _AP_SETTINGS,
        f"connection up {_CON}",
    ]
    assert run.passwd_file is None
    assert run.summary["status"] == "OK"


def test_missing_configured_interface_falls_back_to_the_detected_wifi_device(
    tmp_path: Path,
) -> None:
    run = _run_hotspot(tmp_path, interfaces=("wlan1",), wifi_device="wlan1")

    assert run.returncode == 0, run.log_text()
    assert (
        f"connection add type wifi ifname wlan1 con-name {_CON} autoconnect yes ssid Workshop"
        in run.nmcli_changes()
    )
    assert (run.summary["configured_ifname"], run.summary["effective_ifname"]) == (
        "wlan0",
        "wlan1",
    )


@pytest.mark.parametrize(
    ("setup", "rc", "log_line"),
    [
        pytest.param(
            {"interfaces": (), "wifi_device": ""},
            20,
            "no wifi interface detected",
            id="no-wifi-interface",
        ),
        pytest.param(
            {"flags": ("nm_not_ready",)},
            21,
            "NetworkManager did not become ready",
            id="networkmanager-not-ready",
        ),
        pytest.param(
            {"flags": ("fail_up",)}, 22, f"AP connection bring-up failed for {_CON}", id="up-fails"
        ),
    ],
)
def test_provisioning_failures_exit_with_their_code_and_a_failed_summary(
    tmp_path: Path, setup: dict[str, object], rc: int, log_line: str
) -> None:
    run = _run_hotspot(tmp_path, **setup)

    assert run.returncode == rc
    assert (run.summary["status"], run.summary["rc"]) == ("FAILED", str(rc))
    assert log_line in run.log_text()
    if rc == 21:
        assert run.calls.count("sleep 1") == 19
    if rc != 22:
        assert not any(c.startswith("connection up") for c in run.nmcli_changes())


def test_unexpected_nmcli_failure_is_trapped_with_diagnostics(tmp_path: Path) -> None:
    run = _run_hotspot(tmp_path, flags=("fail_modify",))

    assert run.returncode == 4
    assert (run.summary["status"], run.summary["rc"]) == ("FAILED", "4")
    assert "ERROR rc=4" in run.log_text()
    assert (run.log_dir / "error_nm_dev.txt").exists()
    assert not any(c.startswith("connection up") for c in run.nmcli_changes())
