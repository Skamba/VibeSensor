"""Wi-Fi hotspot self-heal manager.

Monitors hotspot connectivity and automatically recovers from failures
by restarting ``hostapd``/``dnsmasq`` when the hotspot becomes unreachable.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vibesensor.adapters.hotspot.health_probe import (
    HealthState,
    collect_health,
    journalctl_nm_args,
)
from vibesensor.adapters.hotspot.parsers import HealStateStore
from vibesensor.adapters.hotspot.remediation import apply_heals

LOGGER = logging.getLogger("vibesensor.adapters.hotspot.selfheal")


class HotspotSelfHealConfig(Protocol):
    diagnostics_lookback_minutes: int
    min_restart_interval_seconds: int
    state_file: Path


class HotspotApConfig(Protocol):
    ssid: str
    psk: str
    ip: str
    channel: int
    ifname: str
    con_name: str


@dataclass(slots=True)
class CommandResult:
    """Result of a subprocess command run by :class:`CommandRunner`."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Runs system commands via subprocess. Subclass for test stubs."""

    def run(self, argv: list[str], timeout_s: int = 10) -> CommandResult:
        """Execute *argv* as a subprocess and return the result."""
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


def _emit_diagnostics(
    ap: HotspotApConfig,
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
        journalctl_nm_args(lookback_minutes),
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


def _log_summary(status: str, ap: HotspotApConfig, health: HealthState) -> None:
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
    ap: HotspotApConfig,
    self_heal: HotspotSelfHealConfig,
    runner: CommandRunner,
    state_store: HealStateStore,
    diagnostics_only: bool = False,
) -> int:
    """Run one self-heal cycle; return an exit code (0 = ok, 1 = healed, 2 = failed)."""
    if diagnostics_only:
        _emit_diagnostics(ap, self_heal.diagnostics_lookback_minutes, runner, LOGGER)
        return 0

    health = collect_health(ap, self_heal, runner)
    if health.ok:
        _log_summary("ok", ap, health)
        return 0

    _log_summary("degraded", ap, health)
    _emit_diagnostics(ap, self_heal.diagnostics_lookback_minutes, runner, LOGGER)

    actions = apply_heals(ap, self_heal, health, runner, state_store)

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


def run_self_heal(
    ap: HotspotApConfig,
    self_heal: HotspotSelfHealConfig,
    diagnostics_only: bool = False,
) -> int:
    """Run one self-heal cycle with the given configuration."""
    runner = CommandRunner()
    store = HealStateStore(self_heal.state_file)
    return run_self_heal_once(ap, self_heal, runner, store, diagnostics_only=diagnostics_only)
