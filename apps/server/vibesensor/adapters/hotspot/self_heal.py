"""Wi-Fi hotspot self-heal manager.

Monitors hotspot connectivity and attempts recovery with NetworkManager-driven
repairs plus related hotspot diagnostics when the AP becomes degraded.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vibesensor.adapters.hotspot.constants import (
    DIAGNOSTICS_LOOKBACK_MINUTES,
    HOTSPOT_CON_NAME,
    HOTSPOT_IFNAME,
)
from vibesensor.adapters.hotspot.health_probe import (
    HealthState,
    collect_health,
    journalctl_nm_args,
)
from vibesensor.adapters.hotspot.parsers import HealStateStore
from vibesensor.adapters.hotspot.remediation import apply_heals

LOGGER = logging.getLogger("vibesensor.adapters.hotspot.selfheal")


class HotspotCredentials(Protocol):
    """Operator-owned hotspot settings; everything else is in ``hotspot.constants``."""

    ssid: str
    psk: str


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


def _emit_diagnostics(runner: CommandRunner, logger: logging.Logger) -> None:
    commands = [
        ["nmcli", "device", "status"],
        ["nmcli", "general", "status"],
        ["nmcli", "connection", "show", HOTSPOT_CON_NAME],
        ["nmcli", "connection", "show", "--active"],
        ["ip", "addr", "show", "dev", HOTSPOT_IFNAME],
        ["iw", "dev", HOTSPOT_IFNAME, "info"],
        ["rfkill", "list"],
        journalctl_nm_args(DIAGNOSTICS_LOOKBACK_MINUTES),
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


def _log_summary(status: str, health: HealthState) -> None:
    LOGGER.info(
        "hotspot health status=%s active=%s iface=%s ip_ok=%s channel=%s last_error=%s issues=%s",
        status,
        "yes" if health.ap_conn_active else "no",
        HOTSPOT_IFNAME,
        "yes" if health.ip_ok else "no",
        health.channel or "unknown",
        health.last_error_category,
        ",".join(health.issues) if health.issues else "none",
    )


def run_self_heal_once(
    ap: HotspotCredentials,
    runner: CommandRunner,
    state_store: HealStateStore,
    diagnostics_only: bool = False,
) -> int:
    """Run one self-heal cycle; return 0 when healthy/recovered, else 2."""
    if diagnostics_only:
        _emit_diagnostics(runner, LOGGER)
        return 0

    health = collect_health(runner)
    if health.ok:
        _log_summary("ok", health)
        return 0

    _log_summary("degraded", health)
    _emit_diagnostics(runner, LOGGER)

    actions = apply_heals(ap, health, runner, state_store)

    post_heal_health = collect_health(runner)
    status = "healed" if post_heal_health.ok else "failed"

    for action in actions:
        action.helped = post_heal_health.ok
        LOGGER.warning(
            "hotspot heal attempt=%s detected=%s action=%s helped=%s",
            action.name,
            action.detected,
            action.action,
            "yes" if action.helped else "no",
        )

    _log_summary(status, post_heal_health)
    if not post_heal_health.ok:
        _emit_diagnostics(runner, LOGGER)
        return 2
    return 0


def run_self_heal(
    ap: HotspotCredentials,
    state_file: Path,
    diagnostics_only: bool = False,
) -> int:
    """Run one self-heal cycle, persisting restart backoff state in *state_file*."""
    runner = CommandRunner()
    store = HealStateStore(state_file)
    return run_self_heal_once(ap, runner, store, diagnostics_only=diagnostics_only)
