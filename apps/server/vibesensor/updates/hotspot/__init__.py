"""Hotspot infrastructure — Wi-Fi AP monitoring, parsing, and self-heal.

Sub-modules
-----------
- :mod:`~vibesensor.updates.hotspot.parsers` — text-parsing helpers for hostapd,
  dnsmasq, NetworkManager, iw, and rfkill output.
- :mod:`~vibesensor.updates.hotspot.health_probe` — hotspot health snapshot collection.
- :mod:`~vibesensor.updates.hotspot.remediation` — hotspot repair helpers and policy.
- :mod:`~vibesensor.updates.hotspot.self_heal` — hotspot watchdog manager.
"""
