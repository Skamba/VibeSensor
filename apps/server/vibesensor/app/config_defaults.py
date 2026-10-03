"""Runtime defaults for application configuration.

Only settings that differ between deployments (dev, Docker, Pi, isolated test
runtimes) or that operators own (hotspot SSID/PSK) are YAML-configurable. Fixed
tuning values live as constants in the modules that consume them.
"""

from __future__ import annotations

from copy import deepcopy

from vibesensor.common.json_types import JsonObject

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
        "app_log_path": "data/app.log",
    },
    "gps": {"gps_enabled": True},
    "update": {
        "rollback_dir": "/var/lib/vibesensor/rollback",
    },
}


__all__ = ["DEFAULT_CONFIG", "documented_default_config"]


def documented_default_config() -> JsonObject:
    """Return runtime defaults used by config loading and preflight checks."""
    return deepcopy(DEFAULT_CONFIG)
