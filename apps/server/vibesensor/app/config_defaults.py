"""Runtime defaults for application configuration.

Only settings that differ between deployments (dev, Docker, Pi, isolated test
runtimes) or that operators own (hotspot SSID/PSK) are YAML-configurable. Fixed
tuning values live as constants in the modules that consume them.
"""

from __future__ import annotations

from copy import deepcopy

from vibesensor.common.json_types import JsonObject
from vibesensor.recording.lifecycle_state import MAX_RECORDING_DURATION_S

DEFAULT_CONFIG: JsonObject = {
    "ap": {
        "ssid": "VibeSensor",
        "psk": "",
    },
    "server": {"host": "0.0.0.0", "port": 80},
    "udp": {
        "data_host": "0.0.0.0",
        "data_port": 9000,
        "control_host": "0.0.0.0",
        "control_port": 9001,
    },
    "logging": {
        "history_db_path": "data/history.db",
        # Relative to the directory of history_db_path (the data directory).
        "app_log_path": "app.log",
    },
    # gpsd runs on the Pi itself (127.0.0.1); 2947 is its standard TCP port.
    "gps": {"gps_enabled": True, "gpsd_port": 2947},
    # Isolated test runtimes shorten the cap to exercise the auto-stop path.
    "recording": {"max_duration_s": MAX_RECORDING_DURATION_S},
}


__all__ = ["DEFAULT_CONFIG", "documented_default_config"]


def documented_default_config() -> JsonObject:
    """Return runtime defaults used by config loading and preflight checks."""
    return deepcopy(DEFAULT_CONFIG)
