"""Hotspot self-heal remediation helpers and policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.adapters.hotspot.parsers import HealStateStore, parse_active_connection_names

if TYPE_CHECKING:
    from vibesensor.adapters.hotspot.health_probe import HealthState
    from vibesensor.adapters.hotspot.self_heal import (
        CommandRunner,
        HotspotApConfig,
        HotspotSelfHealConfig,
    )

__all__ = ["HealAction", "apply_heals"]

_FALLBACK_CHANNELS: tuple[int, ...] = (1, 6, 11)


@dataclass(slots=True)
class HealAction:
    """Record of a single self-heal action taken to restore hotspot connectivity."""

    name: str
    detected: str
    action: str
    helped: bool


def _ensure_ap_connection(
    ap: HotspotApConfig, runner: CommandRunner, channel: int | None = None
) -> bool:
    configured_channel = channel if channel is not None else ap.channel
    con_names = parse_active_connection_names(
        runner.run(["nmcli", "-t", "-f", "NAME", "connection", "show"], timeout_s=8).stdout,
    )
    if not ap.psk and ap.con_name in con_names:
        # Recreate open AP profiles to guarantee no stale security fields remain.
        runner.run(["nmcli", "connection", "delete", ap.con_name], timeout_s=8)
        con_names = [name for name in con_names if name != ap.con_name]

    if ap.con_name not in con_names:
        added = runner.run(
            [
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
            ],
            timeout_s=10,
        )
        if added.returncode != 0:
            return False

    modify_args = [
        "nmcli",
        "connection",
        "modify",
        ap.con_name,
        "802-11-wireless.mode",
        "ap",
        "802-11-wireless.band",
        "bg",
        "802-11-wireless.channel",
        str(configured_channel),
        "ipv4.method",
        "shared",
        "ipv4.addresses",
        ap.ip,
        "ipv6.method",
        "ignore",
    ]
    if ap.psk:
        modify_args.extend(
            [
                "802-11-wireless-security.key-mgmt",
                "wpa-psk",
                "802-11-wireless-security.psk",
                ap.psk,
            ],
        )

    modified = runner.run(modify_args, timeout_s=10)
    if modified.returncode != 0:
        return False

    up = runner.run(["nmcli", "--wait", "12", "connection", "up", ap.con_name], timeout_s=15)
    return up.returncode == 0


def _bounce_connection(ap: HotspotApConfig, runner: CommandRunner) -> None:
    runner.run(["nmcli", "connection", "down", ap.con_name], timeout_s=8)
    runner.run(["ip", "link", "set", ap.ifname, "up"], timeout_s=5)
    runner.run(["nmcli", "--wait", "10", "connection", "up", ap.con_name], timeout_s=12)


def _recreate_connection(ap: HotspotApConfig, runner: CommandRunner) -> bool:
    runner.run(["nmcli", "connection", "delete", ap.con_name], timeout_s=8)
    return _ensure_ap_connection(ap, runner)


def _handle_port53_conflict(conflict: str, runner: CommandRunner) -> str:
    lowered = conflict.lower()
    if "dnsmasq" in lowered:
        runner.run(["systemctl", "disable", "--now", "dnsmasq.service"], timeout_s=10)
        return "stopped standalone dnsmasq service"

    if "systemd-resolve" in lowered:
        runner.run(
            [
                "/bin/sh",
                "-c",
                "mkdir -p /etc/systemd/resolved.conf.d && "
                "printf '[Resolve]\\nDNSStubListener=no\\n' > "
                "/etc/systemd/resolved.conf.d/vibesensor-no-stub.conf",
            ],
            timeout_s=10,
        )
        runner.run(["systemctl", "restart", "systemd-resolved"], timeout_s=10)
        return "disabled systemd-resolved DNS stub listener"

    return f"detected :53 conflict owner={conflict}; no automatic disruptive action taken"


def apply_heals(
    ap: HotspotApConfig,
    self_heal: HotspotSelfHealConfig,
    health: HealthState,
    runner: CommandRunner,
    state_store: HealStateStore,
) -> list[HealAction]:
    """Apply remediation actions for the current hotspot health snapshot."""
    actions: list[HealAction] = []

    if not health.nm_running:
        if state_store.allow("restart_networkmanager", self_heal.min_restart_interval_seconds):
            runner.run(["systemctl", "restart", "NetworkManager"], timeout_s=15)
            action = "systemctl restart NetworkManager"
        else:
            action = "restart skipped by backoff"
        actions.append(
            HealAction(
                name="restart_networkmanager",
                detected="NetworkManager inactive",
                action=action,
                helped=False,
            ),
        )

    if not health.wifi_radio_on:
        runner.run(["nmcli", "radio", "wifi", "on"], timeout_s=8)
        actions.append(
            HealAction(
                name="wifi_radio_on",
                detected="Wi-Fi radio disabled",
                action="nmcli radio wifi on",
                helped=False,
            ),
        )

    if health.rfkill_blocked:
        runner.run(["rfkill", "unblock", "wifi"], timeout_s=8)
        actions.append(
            HealAction(
                name="rfkill_unblock",
                detected="rfkill blocked",
                action="rfkill unblock wifi",
                helped=False,
            ),
        )

    if not health.iface_up and health.iface_exists:
        runner.run(["ip", "link", "set", ap.ifname, "up"], timeout_s=8)
        actions.append(
            HealAction(
                name="if_up",
                detected="interface down",
                action=f"ip link set {ap.ifname} up",
                helped=False,
            ),
        )

    if not health.ap_conn_exists or not health.ap_conn_active:
        ensured = _ensure_ap_connection(ap, runner)
        if not ensured:
            ensured = _recreate_connection(ap, runner)
        if not ensured:
            for fallback_channel in _FALLBACK_CHANNELS:
                if fallback_channel == ap.channel:
                    continue
                if _ensure_ap_connection(ap, runner, channel=fallback_channel):
                    actions.append(
                        HealAction(
                            name="ap_channel_fallback",
                            detected="configured AP channel failed",
                            action=f"ap recreated on fallback channel {fallback_channel}",
                            helped=False,
                        ),
                    )
                    break
        actions.append(
            HealAction(
                name="ensure_ap_connection",
                detected="AP connection missing/inactive",
                action="ensure AP connection and bring it up",
                helped=False,
            ),
        )

    if health.ap_conn_active and (not health.iface_up or not health.ap_mode):
        _bounce_connection(ap, runner)
        actions.append(
            HealAction(
                name="bounce_ap",
                detected="AP active but interface down or not in AP mode",
                action="nmcli connection down/up and ip link up",
                helped=False,
            ),
        )

    if not health.dhcp_ok:
        if health.port53_conflict:
            message = _handle_port53_conflict(health.port53_conflict, runner)
            actions.append(
                HealAction(
                    name="port53_conflict",
                    detected=f"port 53 conflict ({health.port53_conflict})",
                    action=message,
                    helped=False,
                ),
            )
        _ensure_ap_connection(ap, runner)
        if state_store.allow("restart_networkmanager", self_heal.min_restart_interval_seconds):
            runner.run(["systemctl", "restart", "NetworkManager"], timeout_s=15)
            runner.run(["nmcli", "--wait", "12", "connection", "up", ap.con_name], timeout_s=15)
            action = "re-applied AP connection and restarted NetworkManager"
        else:
            action = "restart skipped by backoff; AP re-applied"
        actions.append(
            HealAction(
                name="dhcp_repair",
                detected="DHCP path unhealthy",
                action=action,
                helped=False,
            ),
        )

    return actions
