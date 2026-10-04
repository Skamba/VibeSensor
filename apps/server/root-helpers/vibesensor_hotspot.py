#!/usr/bin/python3 -I
"""Root-side hotspot helper: settings for ``hotspot_nmcli.sh`` and the periodic watchdog.

``config [CONFIG_PATH]`` prints the hotspot settings as shell assignments for
``hotspot_nmcli.sh`` to ``eval``. SSID and PSK come from the ``ap`` section of
the YAML config; everything else is fixed.

``watchdog`` is one pass of ``vibesensor-hotspot-self-heal.timer``. It checks
whether the NetworkManager hotspot profile is active. When it is not, it
retries ``nmcli connection up`` with backoff, and if that keeps failing it
restarts ``vibesensor-hotspot.service``, which recreates the profile and repairs
rfkill, radio, and DNS/DHCP state (``hotspot_nmcli.sh``).

Both run as root under the system ``python3 -I`` from the root-owned helper
directory (``install_systemd_units.sh``). Keep this script stdlib-only (plus
the distribution's ``python3-yaml``) and never import ``vibesensor`` or anything
from the service user's venv. The fixed values below copy
``vibesensor/hotspot/constants.py``, ``vibesensor/hotspot/captive_portal.py``,
and the ``ap`` defaults in ``vibesensor/app/config_defaults.py``;
``tests/root_helpers/test_vibesensor_hotspot.py`` keeps them in sync.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/vibesensor/config.yaml")
DEFAULT_SSID = "VibeSensor"
DEFAULT_PSK = ""
HOTSPOT_IP = "10.4.0.1/24"
HOTSPOT_CHANNEL = 7
HOTSPOT_IFNAME = "wlan0"
HOTSPOT_CON_NAME = "VibeSensor-AP"
HOTSPOT_PROVISION_UNIT = "vibesensor-hotspot.service"
CAPTIVE_PROBE_HOSTS = (
    "connectivitycheck.gstatic.com",
    "connectivitycheck.android.com",
    "clients3.google.com",
    "connect.rom.miui.com",
    "connectivitycheck.platform.hicloud.com",
    "captive.apple.com",
    "www.msftconnecttest.com",
    "www.msftncsi.com",
    "detectportal.firefox.com",
    "nmcheck.gnome.org",
    "connectivity-check.ubuntu.com",
    "network-test.debian.org",
)

RETRY_DELAYS_S: tuple[float, ...] = (0.0, 5.0, 15.0)
"""Delay before each ``nmcli connection up`` attempt."""
_UP_WAIT_S = 15

LOGGER = logging.getLogger("vibesensor-hotspot")

Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


# -- config -------------------------------------------------------------------


def _warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)


def load_ap_config(config_path: Path) -> dict[str, object]:
    """Return the config's ``ap`` mapping, or ``{}`` (with a warning) when unusable."""
    if not config_path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:
        _warn(f"Failed to import YAML support for {config_path}: {exc}; using defaults.")
        return {}
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        _warn(f"Failed to parse hotspot config {config_path}: {exc}; using defaults.")
        return {}
    if not isinstance(raw, dict):
        _warn(f"Hotspot config {config_path} must contain a top-level mapping; using defaults.")
        return {}
    cfg = raw.get("ap", {}) or {}
    if not isinstance(cfg, dict):
        _warn(f"Hotspot config {config_path} has a non-mapping 'ap' section; using defaults.")
        return {}
    return cfg


def hotspot_exports(config_path: Path) -> dict[str, object]:
    cfg = load_ap_config(config_path)
    address = HOTSPOT_IP.split("/", 1)[0]
    return {
        "SSID": cfg.get("ssid", DEFAULT_SSID),
        "PSK": cfg.get("psk", DEFAULT_PSK),
        "IP": HOTSPOT_IP,
        "CHANNEL": HOTSPOT_CHANNEL,
        "IFNAME": HOTSPOT_IFNAME,
        "CON_NAME": HOTSPOT_CON_NAME,
        "CAPTIVE_DNS_ADDRESS": "/" + "/".join(CAPTIVE_PROBE_HOSTS) + f"/{address}",
    }


def print_exports(config_path: Path) -> int:
    for name, value in hotspot_exports(config_path).items():
        # hotspot_nmcli.sh evals these lines, so quote every value for the shell.
        print(f"{name}={shlex.quote(str(value))}")
    return 0


# -- watchdog -------------------------------------------------------------------


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


def check_hotspot(run: Runner = run_command, sleep: Callable[[float], None] = time.sleep) -> int:
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


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["config"] and len(args) <= 2:
        return print_exports(Path(args[1]) if len(args) == 2 else DEFAULT_CONFIG_PATH)
    if args == ["watchdog"]:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        return check_hotspot()
    print("Usage: vibesensor_hotspot.py config [CONFIG_PATH] | watchdog", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
