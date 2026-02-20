from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.config import APConfig, APSelfHealConfig
from vibesensor.hotspot_self_heal import (
    _ensure_ap_connection,
    CommandResult,
    CommandRunner,
    HealStateStore,
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
            ]
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
    *,
    allow_disable_resolved_stub_listener: bool = False,
) -> APSelfHealConfig:
    return APSelfHealConfig(
        enabled=True,
        interval_seconds=120,
        diagnostics_lookback_minutes=5,
        min_restart_interval_seconds=0,
        allow_disable_resolved_stub_listener=allow_disable_resolved_stub_listener,
        state_file=tmp_path / "hotspot-self-heal-state.json",
    )


def _ap_cfg(tmp_path: Path, *, allow_disable_resolved_stub_listener: bool = False) -> APConfig:
    self_heal = _self_heal_cfg(
        tmp_path, allow_disable_resolved_stub_listener=allow_disable_resolved_stub_listener
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
            _ok(f"NAME  DEVICE\n{ap.con_name}  {ap.ifname}")
        ],
        ("ip", "addr", "show", "dev", ap.ifname): [_ok("3: wlan0\n    inet 10.4.0.1/24")],
        ("rfkill", "list"): [_ok("0: phy0: Wireless LAN\n\tSoft blocked: no\n\tHard blocked: no")],
        ("ip", "link", "show", "dev", ap.ifname): [
            _ok("2: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP")
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
            _ok(f"{ap.con_name}:{ap.ifname}\n")
        ],
        ("iw", "dev", ap.ifname, "info"): [
            _ok("Interface wlan0\n\ttype AP\n\tchannel 7 (2442 MHz)")
        ],
        ("ip", "-4", "addr", "show", "dev", ap.ifname): [
            _ok("3: wlan0\n    inet 10.4.0.1/24 brd 10.4.0.255 scope global wlan0")
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


def test_collect_health_nm_stopped(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("systemctl", "is-active", "NetworkManager")] = [_err("inactive")]
    runner = _FakeRunner(responses)

    state = collect_health(ap, ap.self_heal, runner)

    assert not state.nm_running
    assert "networkmanager_down" in state.issues


def test_collect_health_wifi_radio_off(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("nmcli", "-t", "-f", "WIFI", "general", "status")] = [_ok("disabled")]
    runner = _FakeRunner(responses)

    state = collect_health(ap, ap.self_heal, runner)

    assert not state.wifi_radio_on
    assert "wifi_radio_off" in state.issues


def test_collect_health_rfkill_blocked(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("rfkill", "list")] = [_ok("Soft blocked: yes\nHard blocked: no")]
    runner = _FakeRunner(responses)

    state = collect_health(ap, ap.self_heal, runner)

    assert state.rfkill_blocked
    assert "rfkill_blocked" in state.issues


def test_collect_health_ap_connection_missing(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("nmcli", "-t", "-f", "NAME", "connection", "show")] = [_ok("OtherConn\n")]
    responses[("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active")] = [_ok("")]
    runner = _FakeRunner(responses)

    state = collect_health(ap, ap.self_heal, runner)

    assert not state.ap_conn_exists
    assert "ap_connection_missing" in state.issues


def test_collect_health_ap_present_but_inactive(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active")] = [
        _ok("uplink:wlan0\n")
    ]
    runner = _FakeRunner(responses)

    state = collect_health(ap, ap.self_heal, runner)

    assert state.ap_conn_exists
    assert not state.ap_conn_active
    assert "ap_connection_inactive" in state.issues


def test_collect_health_ap_active_but_interface_down(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("ip", "link", "show", "dev", ap.ifname)] = [
        _ok("2: wlan0: <BROADCAST,MULTICAST> mtu 1500 state DOWN")
    ]
    runner = _FakeRunner(responses)

    state = collect_health(ap, ap.self_heal, runner)

    assert not state.iface_up
    assert "iface_down" in state.issues


def test_collect_health_dhcp_broken_signal(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path)
    responses = _healthy_responses(ap)
    responses[("pgrep", "-af", "dnsmasq")] = [_err(stderr="not found")]
    responses[
        (
            "journalctl",
            "-u",
            "NetworkManager",
            "--since",
            "-5 min",
            "--no-pager",
            "-n",
            "120",
        )
    ] = [_ok("dnsmasq failed to start: no address range available for DHCP request")]
    runner = _FakeRunner(responses)

    state = collect_health(ap, ap.self_heal, runner)

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
            ("nmcli", "connection", "up", ap.con_name, "--wait", "12"): [_ok("")],
        }
    )

    ok = _ensure_ap_connection(ap, runner)
    assert ok
    assert ("nmcli", "connection", "delete", ap.con_name) in runner.commands
    assert _nmcli_modify_cmd(ap) in runner.commands
    assert "802-11-wireless-security.key-mgmt" not in _nmcli_modify_cmd(ap)


def test_run_self_heal_port53_conflict_opt_in_gating(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path, allow_disable_resolved_stub_listener=False)
    responses = _healthy_responses(ap)
    responses[("pgrep", "-af", "dnsmasq")] = [
        _err(stderr="not found"),
        _err(stderr="not found"),
    ]
    responses[("ss", "-ltnup", "sport", "=", ":53")] = [
        _ok('udp   UNCONN 0 0 127.0.0.53:53 0.0.0.0:* users:("systemd-resolved",pid=123,fd=12)'),
        _ok('udp   UNCONN 0 0 127.0.0.53:53 0.0.0.0:* users:("systemd-resolved",pid=123,fd=12)'),
    ]
    responses[("systemctl", "restart", "NetworkManager")] = [_ok(""), _ok("")]
    responses[_nmcli_modify_cmd(ap)] = [_ok("")]
    responses[("nmcli", "connection", "up", ap.con_name, "--wait", "12")] = [_ok(""), _ok("")]
    runner = _FakeRunner(responses)

    result = run_self_heal_once(
        ap,
        ap.self_heal,
        runner,
        HealStateStore(ap.self_heal.state_file),
        diagnostics_only=False,
    )

    assert result == 2
    assert ("systemctl", "restart", "systemd-resolved") not in runner.commands


def test_run_self_heal_port53_conflict_allows_resolved_fix_when_opted_in(tmp_path: Path) -> None:
    ap = _ap_cfg(tmp_path, allow_disable_resolved_stub_listener=True)
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
    responses[("nmcli", "connection", "up", ap.con_name, "--wait", "12")] = [_ok(""), _ok("")]
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
