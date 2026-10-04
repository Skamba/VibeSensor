"""Captive-portal answers for phone/laptop connectivity probes on the hotspot.

When a device joins the hotspot it fetches a well-known probe URL (Android
``generate_204``, Apple ``hotspot-detect.html``, Windows ``connecttest.txt``,
...). The hotspot's DNS (NetworkManager's shared-mode dnsmasq, which serves
only the AP interface) resolves exactly these probe hosts to the Pi, and the
HTTP server answers any request for them with a redirect to the UI. The OS
then reports a sign-in page and opens the VibeSensor UI automatically.

Every other name still resolves normally, and the Pi's own resolver is not
touched, so updates over a Wi-Fi or USB uplink keep working.
"""

from __future__ import annotations

from typing import Final

from vibesensor.hotspot.constants import HOTSPOT_IP

CAPTIVE_PROBE_HOSTS: Final[tuple[str, ...]] = (
    # Android / ChromeOS (and OEM variants)
    "connectivitycheck.gstatic.com",
    "connectivitycheck.android.com",
    "clients3.google.com",
    "connect.rom.miui.com",
    "connectivitycheck.platform.hicloud.com",
    # Apple iOS / macOS
    "captive.apple.com",
    # Windows NCSI
    "www.msftconnecttest.com",
    "www.msftncsi.com",
    # Firefox, GNOME/Ubuntu/Debian NetworkManager
    "detectportal.firefox.com",
    "nmcheck.gnome.org",
    "connectivity-check.ubuntu.com",
    "network-test.debian.org",
)
"""Hostnames of the OS connectivity probes the hotspot answers as a portal."""

HOTSPOT_ADDRESS: Final[str] = HOTSPOT_IP.split("/", 1)[0]

PORTAL_URL: Final[str] = f"http://{HOTSPOT_ADDRESS}/"
"""Where probe requests are redirected: the UI on the hotspot address."""


def dnsmasq_probe_address() -> str:
    """Return the dnsmasq ``address=`` value that points every probe host at the Pi."""
    return "/" + "/".join(CAPTIVE_PROBE_HOSTS) + f"/{HOTSPOT_ADDRESS}"


def is_probe_host(host_header: str | None) -> bool:
    """Whether an HTTP ``Host`` header names a probe host (or one of its subdomains)."""
    if not host_header:
        return False
    host = host_header.rsplit(":", 1)[0].strip().rstrip(".").lower()
    return any(host == probe or host.endswith(f".{probe}") for probe in CAPTIVE_PROBE_HOSTS)
