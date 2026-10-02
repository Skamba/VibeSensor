"""Hotspot infrastructure — Wi-Fi AP monitoring, parsing, and self-heal.

Sub-modules
-----------
- :mod:`~vibesensor.adapters.hotspot.parsers` — text-parsing helpers for hostapd,
  dnsmasq, NetworkManager, iw, and rfkill output.
- :mod:`~vibesensor.adapters.hotspot.health_probe` — hotspot health snapshot collection.
- :mod:`~vibesensor.adapters.hotspot.remediation` — hotspot repair helpers and policy.
- :mod:`~vibesensor.adapters.hotspot.self_heal` — hotspot watchdog manager.
"""
