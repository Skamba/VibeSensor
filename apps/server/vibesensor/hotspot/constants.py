"""Fixed hotspot network settings used by the updater and the captive portal.

Only the SSID and PSK are operator-configurable (``ap.ssid`` / ``ap.psk``). The
root-side ``root-helpers/vibesensor_hotspot.py`` (hotspot provisioning and watchdog)
carries its own copy; ``tests/root_helpers/test_vibesensor_hotspot.py`` keeps them in sync.
"""

from __future__ import annotations

from typing import Final

HOTSPOT_IP: Final[str] = "10.4.0.1/24"
"""Hotspot address/subnet used by NetworkManager shared mode."""

HOTSPOT_IFNAME: Final[str] = "wlan0"
"""Preferred Wi-Fi interface; the hotspot script falls back to a detected Wi-Fi device."""

HOTSPOT_CON_NAME: Final[str] = "VibeSensor-AP"
"""NetworkManager connection profile name for the hotspot."""
