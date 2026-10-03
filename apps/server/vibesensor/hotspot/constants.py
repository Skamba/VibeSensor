"""Fixed hotspot network settings shared by the watchdog, hotspot CLI, and updater.

Only the SSID and PSK are operator-configurable (``ap.ssid`` / ``ap.psk``).
"""

from __future__ import annotations

from typing import Final

HOTSPOT_IP: Final[str] = "10.4.0.1/24"
"""Hotspot address/subnet used by NetworkManager shared mode."""

HOTSPOT_CHANNEL: Final[int] = 7
"""2.4 GHz channel the hotspot profile is provisioned on."""

HOTSPOT_IFNAME: Final[str] = "wlan0"
"""Preferred Wi-Fi interface; the hotspot script falls back to a detected Wi-Fi device."""

HOTSPOT_CON_NAME: Final[str] = "VibeSensor-AP"
"""NetworkManager connection profile name for the hotspot."""

HOTSPOT_PROVISION_UNIT: Final[str] = "vibesensor-hotspot.service"
"""Oneshot unit that (re)provisions the hotspot profile via ``hotspot_nmcli.sh``."""
