from __future__ import annotations

import argparse
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import APConfig, APSelfHealConfig, load_config
from .hotspot_parsers import (
    HealStateStore,
    expected_ip_match,
    nm_log_signals,
    parse_active_conn_device,
    parse_active_connection_names,
    parse_ip,
    parse_iw_info,
    parse_port53_conflict,
    parse_rfkill_blocked,
)

LOGGER = logging.getLogger("vibesensor.hotspot.selfheal")


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(self, argv: list[str], timeout_s: int = 10) -> CommandResult:
        raise NotImplementedError


class SubprocessRunner(CommandRunner):
    def run(self, argv: list[str], timeout_s: int = 10) -> CommandResult:
        try:
            completed = subprocess.run(
                argv,
                check=False,
                text=True,
                capture_output=True,
                timeout=timeout_s,
            )
            return CommandResult(
                returncode=completed.returncode,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
            )
        except FileNotFoundError:
            return CommandResult(returncode=127, stdout="", stderr=f"missing command: {argv[0]}")
        except subprocess.TimeoutExpired:
            return CommandResult(returncode=124, stdout="", stderr=f"timeout: {' '.join(argv)}")


@dataclass(slots=True)
class HealAction:
    name: str
    detected: str
    action: str
    helped: bool


@dataclass(slots=True)
class HealthState:
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


def _find_port53_conflict(runner: CommandRunner) -> str | None:
    ss = runner.run(["ss", "-ltnup", "sport", "=", ":53"], timeout_s=5)
    if ss.returncode != 0:
        return None
    return parse_port53_conflict(ss.stdout)


def collect_health(ap: APConfig, self_heal: APSelfHealConfig, runner: CommandRunner) -> HealthState:
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
        [
            "journalctl",
            "-u",
            "NetworkManager",
            "--since",
            f"-{max(1, self_heal.diagnostics_lookback_minutes)} min",
            "--no-pager",
            "-n",
            "120",
        ],
        timeout_s=8,
    )
    dhcp_log_signal, _ = nm_log_signals(nm_logs.stdout)

    pgrep_dnsmasq = runner.run(["pgrep", "-af", "dnsmasq"], timeout_s=5)
    nm_dnsmasq_running = False
    if pgrep_dnsmasq.returncode == 0:
        for line in pgrep_dnsmasq.stdout.splitlines():
            lowered = line.lower()
            if "networkmanager" in lowered and "dnsmasq" in lowered:
                nm_dnsmasq_running = True
                break
    dhcp_ok = nm_dnsmasq_running and dhcp_log_signal not in {
        "dhcp_no_range",
        "dhcp_dnsmasq_start_failed",
        "port53_conflict",
    }
    if not dhcp_ok:
        issues.append("dhcp_unhealthy")

    conflict = _find_port53_conflict(runner)
    if conflict:
        issues.append("port53_conflict")

    if issues:
        last_error = issues[-1]
    else:
        last_error = "none"

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


def _ensure_ap_connection(ap: APConfig, runner: CommandRunner, channel: int | None = None) -> bool:
    configured_channel = channel if channel is not None else ap.channel
    con_names = parse_active_connection_names(
        runner.run(["nmcli", "-t", "-f", "NAME", "connection", "show"], timeout_s=8).stdout
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
            ["802-11-wireless-security.key-mgmt", "wpa-psk", "802-11-wireless-security.psk", ap.psk]
        )

    modified = runner.run(modify_args, timeout_s=10)
    if modified.returncode != 0:
        return False

    up = runner.run(["nmcli", "connection", "up", ap.con_name, "--wait", "12"], timeout_s=15)
    return up.returncode == 0


def _bounce_connection(ap: APConfig, runner: CommandRunner) -> None:
    runner.run(["nmcli", "connection", "down", ap.con_name], timeout_s=8)
    runner.run(["ip", "link", "set", ap.ifname, "up"], timeout_s=5)
    runner.run(["nmcli", "connection", "up", ap.con_name, "--wait", "10"], timeout_s=12)


def _recreate_connection(ap: APConfig, runner: CommandRunner) -> bool:
    runner.run(["nmcli", "connection", "delete", ap.con_name], timeout_s=8)
    return _ensure_ap_connection(ap, runner)


def _handle_port53_conflict(
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


def _emit_diagnostics(
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


def _log_summary(status: str, ap: APConfig, health: HealthState) -> None:
    LOGGER.info(
        "hotspot health status=%s active=%s iface=%s ip_ok=%s channel=%s last_error=%s issues=%s",
        status,
        "yes" if health.ap_conn_active else "no",
        ap.ifname,
        "yes" if health.ip_ok else "no",
        health.channel or "unknown",
        health.last_error_category,
        ",".join(health.issues) if health.issues else "none",
    )


def run_self_heal_once(
    ap: APConfig,
    self_heal: APSelfHealConfig,
    runner: CommandRunner,
    state_store: HealStateStore,
    diagnostics_only: bool = False,
) -> int:
    if diagnostics_only:
        _emit_diagnostics(ap, self_heal.diagnostics_lookback_minutes, runner, LOGGER)
        return 0

    health = collect_health(ap, self_heal, runner)
    if health.ok:
        _log_summary("ok", ap, health)
        return 0

    _log_summary("degraded", ap, health)
    _emit_diagnostics(ap, self_heal.diagnostics_lookback_minutes, runner, LOGGER)

    actions: list[HealAction] = []
    if not health.nm_running:
        if state_store.allow("restart_networkmanager", self_heal.min_restart_interval_seconds):
            runner.run(["systemctl", "restart", "NetworkManager"], timeout_s=15)
            actions.append(
                HealAction(
                    name="restart_networkmanager",
                    detected="NetworkManager inactive",
                    action="systemctl restart NetworkManager",
                    helped=False,
                )
            )
        else:
            actions.append(
                HealAction(
                    name="restart_networkmanager",
                    detected="NetworkManager inactive",
                    action="restart skipped by backoff",
                    helped=False,
                )
            )

    if not health.wifi_radio_on:
        runner.run(["nmcli", "radio", "wifi", "on"], timeout_s=8)
        actions.append(
            HealAction(
                name="wifi_radio_on",
                detected="Wi-Fi radio disabled",
                action="nmcli radio wifi on",
                helped=False,
            )
        )

    if health.rfkill_blocked:
        runner.run(["rfkill", "unblock", "wifi"], timeout_s=8)
        actions.append(
            HealAction(
                name="rfkill_unblock",
                detected="rfkill blocked",
                action="rfkill unblock wifi",
                helped=False,
            )
        )

    if not health.iface_up and health.iface_exists:
        runner.run(["ip", "link", "set", ap.ifname, "up"], timeout_s=8)
        actions.append(
            HealAction(
                name="if_up",
                detected="interface down",
                action=f"ip link set {ap.ifname} up",
                helped=False,
            )
        )

    if not health.ap_conn_exists or not health.ap_conn_active:
        ensured = _ensure_ap_connection(ap, runner)
        if not ensured:
            ensured = _recreate_connection(ap, runner)
        if not ensured:
            for fallback_channel in [1, 6, 11]:
                if fallback_channel == ap.channel:
                    continue
                if _ensure_ap_connection(ap, runner, channel=fallback_channel):
                    actions.append(
                        HealAction(
                            name="ap_channel_fallback",
                            detected="configured AP channel failed",
                            action=f"ap recreated on fallback channel {fallback_channel}",
                            helped=False,
                        )
                    )
                    ensured = True
                    break
        actions.append(
            HealAction(
                name="ensure_ap_connection",
                detected="AP connection missing/inactive",
                action="ensure AP connection and bring it up",
                helped=False,
            )
        )

    if health.ap_conn_active and (not health.iface_up or not health.ap_mode):
        _bounce_connection(ap, runner)
        actions.append(
            HealAction(
                name="bounce_ap",
                detected="AP active but interface down or not in AP mode",
                action="nmcli connection down/up and ip link up",
                helped=False,
            )
        )

    if not health.dhcp_ok:
        if health.port53_conflict:
            message = _handle_port53_conflict(health.port53_conflict, self_heal, runner)
            actions.append(
                HealAction(
                    name="port53_conflict",
                    detected=f"port 53 conflict ({health.port53_conflict})",
                    action=message,
                    helped=False,
                )
            )
        _ensure_ap_connection(ap, runner)
        if state_store.allow("restart_networkmanager", self_heal.min_restart_interval_seconds):
            runner.run(["systemctl", "restart", "NetworkManager"], timeout_s=15)
            runner.run(["nmcli", "connection", "up", ap.con_name, "--wait", "12"], timeout_s=15)
            actions.append(
                HealAction(
                    name="dhcp_repair",
                    detected="DHCP path unhealthy",
                    action="re-applied AP connection and restarted NetworkManager",
                    helped=False,
                )
            )
        else:
            actions.append(
                HealAction(
                    name="dhcp_repair",
                    detected="DHCP path unhealthy",
                    action="restart skipped by backoff; AP re-applied",
                    helped=False,
                )
            )

    healed = collect_health(ap, self_heal, runner)
    status = "healed" if healed.ok else "failed"

    for action in actions:
        action.helped = healed.ok
        LOGGER.warning(
            "hotspot heal attempt=%s detected=%s action=%s helped=%s",
            action.name,
            action.detected,
            action.action,
            "yes" if action.helped else "no",
        )

    _log_summary(status, ap, healed)
    if not healed.ok:
        _emit_diagnostics(ap, self_heal.diagnostics_lookback_minutes, runner, LOGGER)
        return 2
    return 0


def run_self_heal(config_path: Path, diagnostics_only: bool = False) -> int:
    cfg = load_config(config_path)
    ap = cfg.ap
    self_heal = cfg.ap.self_heal
    runner = SubprocessRunner()
    store = HealStateStore(self_heal.state_file)
    return run_self_heal_once(ap, self_heal, runner, store, diagnostics_only=diagnostics_only)


def main() -> None:
    parser = argparse.ArgumentParser(description="VibeSensor hotspot health check and self-healing")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/vibesensor/config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--mode",
        choices=["check-heal", "diagnostics"],
        default="check-heal",
        help="check-heal: health check + remediation, diagnostics: collect diagnostics only",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.mode == "diagnostics":
        raise SystemExit(run_self_heal(args.config, diagnostics_only=True))
    raise SystemExit(run_self_heal(args.config, diagnostics_only=False))


if __name__ == "__main__":
    main()
