"""Hotspot infrastructure — Wi-Fi AP monitoring, parsing, and self-heal.

Sub-modules
-----------
- :mod:`~vibesensor.adapters.hotspot.parsers` — text-parsing helpers for hostapd,
  dnsmasq, NetworkManager, iw, and rfkill output.
- :mod:`~vibesensor.adapters.hotspot.health_probe` — hotspot health snapshot collection.
- :mod:`~vibesensor.adapters.hotspot.remediation` — hotspot repair helpers and policy.
- :mod:`~vibesensor.adapters.hotspot.self_heal` — hotspot watchdog manager.
"""

from vibesensor.adapters.hotspot.parsers import (
    HealStateStore,
    expected_ip_match,
    nm_log_signals,
    parse_active_conn_device,
    parse_active_connection_names,
    parse_ip,
    parse_iw_info,
    parse_port53_conflict,
    parse_rfkill_blocked,
)
from vibesensor.adapters.hotspot.self_heal import (
    CommandResult,
    CommandRunner,
)

__all__ = [
    "CommandResult",
    "CommandRunner",
    "HealStateStore",
    "expected_ip_match",
    "nm_log_signals",
    "parse_active_conn_device",
    "parse_active_connection_names",
    "parse_ip",
    "parse_iw_info",
    "parse_port53_conflict",
    "parse_rfkill_blocked",
]
