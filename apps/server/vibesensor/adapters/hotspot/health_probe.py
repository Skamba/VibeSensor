"""Hotspot health probe collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vibesensor.adapters.hotspot.parsers import (
    expected_ip_match,
    nm_log_signals,
    parse_active_conn_device,
    parse_active_connection_names,
    parse_ip,
    parse_iw_info,
    parse_port53_conflict,
    parse_rfkill_blocked,
)

if TYPE_CHECKING:
    from vibesensor.adapters.hotspot.self_heal import (
        CommandRunner,
        HotspotApConfig,
        HotspotSelfHealConfig,
    )

__all__ = ["HealthState", "collect_health"]

_DHCP_BAD_SIGNALS: frozenset[str] = frozenset(
    {"dhcp_no_range", "dhcp_dnsmasq_start_failed", "port53_conflict"},
)


@dataclass(slots=True)
class HealthState:
    """Snapshot of the current Wi-Fi hotspot health collected from system commands."""

    nm_running: bool
    wifi_radio_on: bool
    rfkill_blocked: bool
    iface_exists: bool
    iface_up: bool
    ap_conn_exists: bool
    ap_conn_active: bool
    ap_mode: bool
    ip_ok: bool
    dhcp_ok: bool
    channel: str | None
    last_error_category: str
    dhcp_log_signal: str | None = None
    port53_conflict: str | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.nm_running
            and self.wifi_radio_on
            and not self.rfkill_blocked
            and self.iface_exists
            and self.iface_up
            and self.ap_conn_exists
            and self.ap_conn_active
            and self.ap_mode
            and self.ip_ok
            and self.dhcp_ok
        )


def journalctl_nm_args(lookback_minutes: int) -> list[str]:
    """Build journalctl argv for NetworkManager log retrieval."""
    return [
        "journalctl",
        "-u",
        "NetworkManager",
        "--since",
        f"-{max(1, lookback_minutes)} min",
        "--no-pager",
        "-n",
        "120",
    ]


def _find_port53_conflict(runner: CommandRunner) -> str | None:
    ss = runner.run(["ss", "-ltnup", "sport", "=", ":53"], timeout_s=5)
    if ss.returncode != 0:
        return None
    return parse_port53_conflict(ss.stdout)


def collect_health(
    ap: HotspotApConfig,
    self_heal: HotspotSelfHealConfig,
    runner: CommandRunner,
) -> HealthState:
    """Collect the current hotspot health state by running diagnostic commands."""
    issues: list[str] = []

    nm_active = runner.run(["systemctl", "is-active", "NetworkManager"], timeout_s=5)
    nm_running = nm_active.returncode == 0 and nm_active.stdout.strip() == "active"
    if not nm_running:
        issues.append("networkmanager_down")

    wifi_state = runner.run(["nmcli", "-t", "-f", "WIFI", "general", "status"], timeout_s=5)
    wifi_radio_on = wifi_state.returncode == 0 and wifi_state.stdout.strip().lower() == "enabled"
    if not wifi_radio_on:
        issues.append("wifi_radio_off")

    rfkill_blocked = False
    rfkill_check = runner.run(["rfkill", "list"], timeout_s=5)
    if rfkill_check.returncode == 0:
        rfkill_blocked = parse_rfkill_blocked(rfkill_check.stdout)
    if rfkill_blocked:
        issues.append("rfkill_blocked")

    iface = runner.run(["ip", "link", "show", "dev", ap.ifname], timeout_s=5)
    iface_exists = iface.returncode == 0
    iface_up = iface_exists and " state UP " in f" {iface.stdout} "
    if not iface_exists:
        issues.append("iface_missing")
    elif not iface_up:
        issues.append("iface_down")

    con_list = runner.run(["nmcli", "-t", "-f", "NAME", "connection", "show"], timeout_s=5)
    con_names = parse_active_connection_names(con_list.stdout)
    ap_conn_exists = ap.con_name in con_names
    if not ap_conn_exists:
        issues.append("ap_connection_missing")

    active = runner.run(
        ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
        timeout_s=5,
    )
    ap_conn_active, active_device = parse_active_conn_device(ap.con_name, active.stdout)
    if not ap_conn_active:
        issues.append("ap_connection_inactive")
    elif active_device and active_device != ap.ifname:
        issues.append("ap_active_on_wrong_if")

    iw_info = runner.run(["iw", "dev", ap.ifname, "info"], timeout_s=5)
    ap_mode = False
    channel = None
    if iw_info.returncode == 0:
        ap_mode, channel = parse_iw_info(iw_info.stdout)
    if ap_conn_active and not ap_mode:
        issues.append("iface_not_ap_mode")

    ip_show = runner.run(["ip", "-4", "addr", "show", "dev", ap.ifname], timeout_s=5)
    actual_ip = parse_ip(ip_show.stdout) if ip_show.returncode == 0 else None
    ip_ok = expected_ip_match(ap.ip, actual_ip)
    if not ip_ok:
        issues.append("ip_mismatch")

    nm_logs = runner.run(
        journalctl_nm_args(self_heal.diagnostics_lookback_minutes),
        timeout_s=8,
    )
    dhcp_log_signal, _ = nm_log_signals(nm_logs.stdout)

    pgrep_dnsmasq = runner.run(["pgrep", "-af", "dnsmasq"], timeout_s=5)
    nm_dnsmasq_running = pgrep_dnsmasq.returncode == 0 and any(
        "networkmanager" in line.lower() and "dnsmasq" in line.lower()
        for line in pgrep_dnsmasq.stdout.splitlines()
    )
    dhcp_ok = nm_dnsmasq_running and dhcp_log_signal not in _DHCP_BAD_SIGNALS
    if not dhcp_ok:
        issues.append("dhcp_unhealthy")

    conflict = _find_port53_conflict(runner)
    if conflict:
        issues.append("port53_conflict")

    last_error = issues[-1] if issues else "none"

    return HealthState(
        nm_running=nm_running,
        wifi_radio_on=wifi_radio_on,
        rfkill_blocked=rfkill_blocked,
        iface_exists=iface_exists,
        iface_up=iface_up,
        ap_conn_exists=ap_conn_exists,
        ap_conn_active=ap_conn_active,
        ap_mode=ap_mode,
        ip_ok=ip_ok,
        dhcp_ok=dhcp_ok,
        channel=channel,
        last_error_category=last_error,
        dhcp_log_signal=dhcp_log_signal,
        port53_conflict=conflict,
        issues=issues,
    )
