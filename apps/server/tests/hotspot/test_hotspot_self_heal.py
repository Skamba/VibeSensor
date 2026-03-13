from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from vibesensor.config import APConfig, APSelfHealConfig
from vibesensor.hotspot.self_heal import (
    CommandResult,
    CommandRunner,
    HealStateStore,
    _ensure_ap_connection,
    collect_health,
    run_self_heal_once,
)


@dataclass
class _Sequence:
    values: list[CommandResult]

    def take(self) -> CommandResult:
        if len(self.values) == 1:
            return self.values[0]
        return self.values.pop(0)


class _FakeRunner(CommandRunner):
    def __init__(self, responses: dict[tuple[str, ...], list[CommandResult]]) -> None:
        self._responses = {k: _Sequence(v) for k, v in responses.items()}
        self.commands: list[tuple[str, ...]] = []

    def run(self, argv: list[str], timeout_s: int = 10) -> CommandResult:
        cmd = tuple(argv)
        self.commands.append(cmd)
        if cmd in self._responses:
            return self._responses[cmd].take()
        raise AssertionError(f"Unexpected command: {cmd}")


def _ok(stdout: str = "") -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def _err(stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(returncode=1, stdout=stdout, stderr=stderr)


def _nmcli_modify_cmd(ap: APConfig) -> tuple[str, ...]:
    base = [
        "nmcli",
        "connection",
        "modify",
        ap.con_name,
        "802-11-wireless.mode",
        "ap",
        "802-11-wireless.band",
        "bg",
        "802-11-wireless.channel",
        "7",
        "ipv4.method",
        "shared",
        "ipv4.addresses",
        ap.ip,
        "ipv6.method",
        "ignore",
    ]
    if ap.psk:
        base.extend(
            [
                "802-11-wireless-security.key-mgmt",
                "wpa-psk",
                "802-11-wireless-security.psk",
                ap.psk,
            ],
        )
    return tuple(base)


def _resolved_stub_write_cmd() -> tuple[str, ...]:
    return (
        "/bin/sh",
        "-c",
        "mkdir -p /etc/systemd/resolved.conf.d && "
        "printf '[Resolve]\\nDNSStubListener=no\\n' > "
        "/etc/systemd/resolved.conf.d/vibesensor-no-stub.conf",
    )


def _self_heal_cfg(
    tmp_path: Path,
) -> APSelfHealConfig:
    return APSelfHealConfig(
        enabled=True,
        diagnostics_lookback_minutes=5,
        min_restart_interval_seconds=0,
        state_file=tmp_path / "hotspot-self-heal-state.json",
    )


def _ap_cfg(tmp_path: Path) -> APConfig:
    self_heal = _self_heal_cfg(
        tmp_path,
    )
    return APConfig(
        ssid="VibeSensor",
        psk="",
        ip="10.4.0.1/24",
        channel=7,
        ifname="wlan0",
        con_name="VibeSensor-AP",
        self_heal=self_heal,
    )


def _healthy_responses(ap: APConfig) -> dict[tuple[str, ...], list[CommandResult]]:
    nm_dnsmasq = (
        "123 dnsmasq --conf-file=/dev/null --enable-dbus=org.freedesktop.NetworkManager.dnsmasq"
    )
    return {
        ("systemctl", "is-active", "NetworkManager"): [_ok("active")],
        ("nmcli", "-t", "-f", "WIFI", "general", "status"): [_ok("enabled")],
        ("nmcli", "device", "status"): [_ok("DEVICE  TYPE  STATE  CONNECTION")],
        ("nmcli", "general", "status"): [_ok("STATE connected")],
        ("nmcli", "connection", "show", ap.con_name): [_ok("connection.id:VibeSensor-AP")],
        ("nmcli", "connection", "show", "--active"): [
            _ok(f"NAME  DEVICE\n{ap.con_name}  {ap.ifname}"),
        ],
        ("ip", "addr", "show", "dev", ap.ifname): [_ok("3: wlan0\n    inet 10.4.0.1/24")],
        ("rfkill", "list"): [_ok("0: phy0: Wireless LAN\n\tSoft blocked: no\n\tHard blocked: no")],
        ("ip", "link", "show", "dev", ap.ifname): [
            _ok("2: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP"),
        ],
        ("nmcli", "-t", "-f", "NAME", "connection", "show"): [_ok(f"{ap.con_name}\n")],
        ("nmcli", "connection", "delete", ap.con_name): [_ok("")],
        (
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            ap.ifname,
            "con-name",
            ap.con_name,
            "autoconnect",
            "yes",
            "ssid",
            ap.ssid,
        ): [_ok("")],
        ("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"): [
            _ok(f"{ap.con_name}:{ap.ifname}\n"),
        ],
        ("iw", "dev", ap.ifname, "info"): [
            _ok("Interface wlan0\n\ttype AP\n\tchannel 7 (2442 MHz)"),
        ],
        ("ip", "-4", "addr", "show", "dev", ap.ifname): [
            _ok("3: wlan0\n    inet 10.4.0.1/24 brd 10.4.0.255 scope global wlan0"),
        ],
        (
            "journalctl",
            "-u",
            "NetworkManager",
            "--since",
            "-5 min",
            "--no-pager",
            "-n",
            "120",
        ): [_ok("all good")],
        ("pgrep", "-af", "dnsmasq"): [_ok(nm_dnsmasq)],
        ("ss", "-ltnup", "sport", "=", ":53"): [_ok("")],
    }


def _collect_health_for(
    tmp_path: Path,
    overrides: dict[tuple[str, ...], list[CommandResult]] | None = None,
):
    """Create default AP config, apply response overrides, return health state."""
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    if overrides:
        responses.update(overrides)
    runner = _FakeRunner(responses)
    return collect_health(ap, ap.self_heal, runner)


@pytest.mark.parametrize(
    ("overrides", "attr", "expected", "issue"),
    [
        pytest.param(
            {("systemctl", "is-active", "NetworkManager"): [_err("inactive")]},
            "nm_running",
            False,
            "networkmanager_down",
            id="nm_stopped",
        ),
        pytest.param(
            {("nmcli", "-t", "-f", "WIFI", "general", "status"): [_ok("disabled")]},
            "wifi_radio_on",
            False,
            "wifi_radio_off",
            id="wifi_radio_off",
        ),
        pytest.param(
            {("rfkill", "list"): [_ok("Soft blocked: yes\nHard blocked: no")]},
            "rfkill_blocked",
            True,
            "rfkill_blocked",
            id="rfkill_blocked",
        ),
        pytest.param(
            {
                ("nmcli", "-t", "-f", "NAME", "connection", "show"): [_ok("OtherConn\n")],
                ("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"): [_ok("")],
            },
            "ap_conn_exists",
            False,
            "ap_connection_missing",
            id="ap_connection_missing",
        ),
        pytest.param(
            {
                ("ip", "link", "show", "dev", "wlan0"): [
                    _ok("2: wlan0: <BROADCAST,MULTICAST> mtu 1500 state DOWN"),
                ],
            },
            "iface_up",
            False,
            "iface_down",
            id="iface_down",
        ),
    ],
)
def test_collect_health_single_fault(
    tmp_path: Path,
    overrides: dict,
    attr: str,
    expected: bool,
    issue: str,
) -> None:
    state = _collect_health_for(tmp_path, overrides)
    assert getattr(state, attr) is expected
    assert issue in state.issues


def test_collect_health_ap_present_but_inactive(tmp_path: Path) -> None:
    state = _collect_health_for(
        tmp_path,
        {
            ("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"): [
                _ok("uplink:wlan0\n"),
            ],
        },
    )
    assert state.ap_conn_exists
    assert not state.ap_conn_active
    assert "ap_connection_inactive" in state.issues


def test_collect_health_dhcp_broken_signal(tmp_path: Path) -> None:
    state = _collect_health_for(
        tmp_path,
        {
            ("pgrep", "-af", "dnsmasq"): [_err(stderr="not found")],
            (
                "journalctl",
                "-u",
                "NetworkManager",
                "--since",
                "-5 min",
                "--no-pager",
                "-n",
                "120",
            ): [_ok("dnsmasq failed to start: no address range available for DHCP request")],
        },
    )
    assert not state.dhcp_ok
    assert state.dhcp_log_signal == "dhcp_no_range"


def test_run_self_heal_restarts_networkmanager_when_stopped(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("systemctl", "is-active", "NetworkManager")] = [_err("inactive"), _ok("active")]
    responses[("systemctl", "restart", "NetworkManager")] = [_ok("")]
    runner = _FakeRunner(responses)

    result = run_self_heal_once(
        ap,
        ap.self_heal,
        runner,
        HealStateStore(ap.self_heal.state_file),
        diagnostics_only=False,
    )

    assert result == 0
    assert ("systemctl", "restart", "NetworkManager") in runner.commands


def test_ensure_ap_connection_open_mode_recreates_without_security_keys(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    runner = _FakeRunner(
        {
            ("nmcli", "-t", "-f", "NAME", "connection", "show"): [_ok(f"{ap.con_name}\n")],
            ("nmcli", "connection", "delete", ap.con_name): [_ok("")],
            (
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                ap.ifname,
                "con-name",
                ap.con_name,
                "autoconnect",
                "yes",
                "ssid",
                ap.ssid,
            ): [_ok("")],
            _nmcli_modify_cmd(ap): [_ok("")],
            ("nmcli", "--wait", "12", "connection", "up", ap.con_name): [_ok("")],
        },
    )

    ok = _ensure_ap_connection(ap, runner)
    assert ok
    assert ("nmcli", "connection", "delete", ap.con_name) in runner.commands
    assert _nmcli_modify_cmd(ap) in runner.commands
    assert "802-11-wireless-security.key-mgmt" not in _nmcli_modify_cmd(ap)


def test_run_self_heal_port53_conflict_disables_resolved_stub(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("pgrep", "-af", "dnsmasq")] = [
        _err(stderr="not found"),
        _ok("123 dnsmasq --enable-dbus=org.freedesktop.NetworkManager.dnsmasq"),
    ]
    responses[("ss", "-ltnup", "sport", "=", ":53")] = [
        _ok('udp   UNCONN 0 0 127.0.0.53:53 0.0.0.0:* users:("systemd-resolved",pid=123,fd=12)'),
        _ok(""),
    ]
    responses[("systemctl", "restart", "systemd-resolved")] = [_ok("")]
    responses[_resolved_stub_write_cmd()] = [_ok("")]
    responses[("systemctl", "restart", "NetworkManager")] = [_ok("")]
    responses[_nmcli_modify_cmd(ap)] = [_ok("")]
    responses[("nmcli", "--wait", "12", "connection", "up", ap.con_name)] = [_ok(""), _ok("")]
    runner = _FakeRunner(responses)

    result = run_self_heal_once(
        ap,
        ap.self_heal,
        runner,
        HealStateStore(ap.self_heal.state_file),
        diagnostics_only=False,
    )

    assert result == 0
    assert ("systemctl", "restart", "systemd-resolved") in runner.commands
