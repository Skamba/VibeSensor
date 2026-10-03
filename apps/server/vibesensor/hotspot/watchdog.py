"""Periodic hotspot watchdog run by ``vibesensor-hotspot-self-heal.timer``.

Each run checks whether the NetworkManager hotspot profile is active. When it
is not, the watchdog retries ``nmcli connection up`` with backoff, and if that
keeps failing it restarts the hotspot provisioning unit, which recreates the
profile and repairs rfkill, radio, and DNS/DHCP state (``hotspot_nmcli.sh``).
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable, Sequence

from vibesensor.hotspot.constants import (
    HOTSPOT_CON_NAME,
    HOTSPOT_IFNAME,
    HOTSPOT_PROVISION_UNIT,
)

__all__ = ["RETRY_DELAYS_S", "check_hotspot", "run_command"]

LOGGER = logging.getLogger(__name__)

RETRY_DELAYS_S: tuple[float, ...] = (0.0, 5.0, 15.0)
"""Delay before each ``nmcli connection up`` attempt."""

_UP_WAIT_S = 15

Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def run_command(argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    """Run *argv*; missing binaries and timeouts become non-zero results."""
    try:
        return subprocess.run(
            list(argv), check=False, capture_output=True, text=True, timeout=timeout_s
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(argv), 127, "", str(exc))


def _active_connections(run: Runner) -> list[tuple[str, str]] | None:
    """Return ``(name, device)`` rows for active NetworkManager connections."""
    result = run(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"], 10)
    if result.returncode != 0:
        return None
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        name, _, device = line.strip().rpartition(":")
        if name:
            rows.append((name, device))
    return rows


def check_hotspot(
    run: Runner = run_command,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Bring the hotspot back when it is down; return 0 when healthy or recovered."""
    active = _active_connections(run)
    if active is None:
        LOGGER.warning("NetworkManager did not answer; re-provisioning the hotspot")
        return _reprovision(run)
    if any(name == HOTSPOT_CON_NAME for name, _ in active):
        return 0
    # The updater temporarily replaces the hotspot with its Wi-Fi uplink on the
    # same interface; it restores the hotspot itself when the update ends.
    owners = [name for name, device in active if device == HOTSPOT_IFNAME]
    if owners:
        LOGGER.info("%s is in use by %s; leaving the hotspot down", HOTSPOT_IFNAME, owners[0])
        return 0

    for attempt, delay_s in enumerate(RETRY_DELAYS_S, start=1):
        if delay_s:
            sleep(delay_s)
        up = run(["nmcli", "--wait", str(_UP_WAIT_S), "connection", "up", HOTSPOT_CON_NAME], 30)
        if up.returncode == 0:
            LOGGER.warning("Hotspot was down; brought it up on attempt %d", attempt)
            return 0
        LOGGER.warning(
            "Hotspot up attempt %d failed (rc=%d): %s",
            attempt,
            up.returncode,
            (up.stderr or up.stdout).strip(),
        )
    return _reprovision(run)


def _reprovision(run: Runner) -> int:
    result = run(["systemctl", "restart", "--no-block", HOTSPOT_PROVISION_UNIT], 30)
    if result.returncode != 0:
        LOGGER.error("Could not restart %s: %s", HOTSPOT_PROVISION_UNIT, result.stderr.strip())
        return 2
    LOGGER.warning("Restarted %s to re-provision the hotspot", HOTSPOT_PROVISION_UNIT)
    return 1
