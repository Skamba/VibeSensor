"""Fixed hotspot network settings shared by the self-heal watchdog, CLI, and updater.

Only the SSID and PSK are operator-configurable (``ap.ssid`` / ``ap.psk``).
"""

from __future__ import annotations

from typing import Final

HOTSPOT_IP: Final[str] = "10.4.0.1/24"
"""Hotspot address/subnet used by NetworkManager shared mode."""

HOTSPOT_CHANNEL: Final[int] = 7
"""Preferred 2.4 GHz channel; self-heal falls back to 1/6/11 when it fails."""

HOTSPOT_IFNAME: Final[str] = "wlan0"
"""Preferred Wi-Fi interface; the hotspot script falls back to a detected Wi-Fi device."""

HOTSPOT_CON_NAME: Final[str] = "VibeSensor-AP"
"""NetworkManager connection profile name for the hotspot."""

DIAGNOSTICS_LOOKBACK_MINUTES: Final[int] = 5
"""NetworkManager journal window collected with hotspot diagnostics."""

MIN_RESTART_INTERVAL_S: Final[int] = 120
"""Minimum seconds between self-heal NetworkManager restarts."""
