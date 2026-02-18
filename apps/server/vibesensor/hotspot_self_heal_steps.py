from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import APConfig, APSelfHealConfig

if TYPE_CHECKING:
    from .hotspot_self_heal import CommandRunner


def ensure_ap_connection(ap: APConfig, runner: CommandRunner, channel: int | None = None) -> bool:
    configured_channel = channel if channel is not None else ap.channel
    con_list = runner.run(["nmcli", "-t", "-f", "NAME", "connection", "show"], timeout_s=8)
    con_names = [line.strip() for line in con_list.stdout.splitlines() if line.strip()]
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

    modified = runner.run(
        [
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
            "802-11-wireless-security.key-mgmt",
            "wpa-psk",
            "802-11-wireless-security.psk",
            ap.psk,
            "ipv4.method",
            "shared",
            "ipv4.addresses",
            ap.ip,
            "ipv6.method",
            "ignore",
        ],
        timeout_s=10,
    )
    if modified.returncode != 0:
        return False

    up = runner.run(["nmcli", "connection", "up", ap.con_name, "--wait", "12"], timeout_s=15)
    return up.returncode == 0


def bounce_connection(ap: APConfig, runner: CommandRunner) -> None:
    runner.run(["nmcli", "connection", "down", ap.con_name], timeout_s=8)
    runner.run(["ip", "link", "set", ap.ifname, "up"], timeout_s=5)
    runner.run(["nmcli", "connection", "up", ap.con_name, "--wait", "10"], timeout_s=12)


def recreate_connection(ap: APConfig, runner: CommandRunner) -> bool:
    runner.run(["nmcli", "connection", "delete", ap.con_name], timeout_s=8)
    return ensure_ap_connection(ap, runner)


def handle_port53_conflict(
    conflict: str,
    self_heal: APSelfHealConfig,
    runner: CommandRunner,
) -> str:
    lowered = conflict.lower()
    if "dnsmasq" in lowered:
        runner.run(["systemctl", "disable", "--now", "dnsmasq.service"], timeout_s=10)
        return "stopped standalone dnsmasq service"

    if "systemd-resolved" in lowered or "systemd-resolve" in lowered:
        if self_heal.allow_disable_resolved_stub_listener:
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
        return (
            "detected systemd-resolved :53 conflict; set "
            "ap.self_heal.allow_disable_resolved_stub_listener=true"
            " to allow automated resolved reconfiguration"
        )

    return f"detected :53 conflict owner={conflict}; no automatic disruptive action taken"


def emit_diagnostics(
    ap: APConfig,
    lookback_minutes: int,
    runner: CommandRunner,
    logger: logging.Logger,
) -> None:
    commands = [
        ["nmcli", "device", "status"],
        ["nmcli", "general", "status"],
        ["nmcli", "connection", "show", ap.con_name],
        ["nmcli", "connection", "show", "--active"],
        ["ip", "addr", "show", "dev", ap.ifname],
        ["iw", "dev", ap.ifname, "info"],
        ["rfkill", "list"],
        [
            "journalctl",
            "-u",
            "NetworkManager",
            "--since",
            f"-{max(1, lookback_minutes)} min",
            "--no-pager",
            "-n",
            "120",
        ],
    ]

    logger.warning("hotspot diagnostics begin")
    for command in commands:
        res = runner.run(command, timeout_s=10)
        logger.warning(
            "diag cmd=%s rc=%s stdout=%s stderr=%s",
            " ".join(command),
            res.returncode,
            res.stdout,
            res.stderr,
        )
    logger.warning("hotspot diagnostics end")
