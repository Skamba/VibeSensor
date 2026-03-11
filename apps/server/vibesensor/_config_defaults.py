"""Default configuration values for VibeSensor.

Separated from ``config.py`` to keep the data-model and loading logic
in the main module while the large defaults dict lives here.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Final

from .json_types import JsonObject, is_json_object

NETWORK_PORTS: Final[dict[str, int]] = {
    "server_udp_data": 9000,
    "server_udp_control": 9001,
    "firmware_control_port_base": 9010,
}

DEFAULT_UDP_DATA_PORT = int(NETWORK_PORTS["server_udp_data"])
DEFAULT_UDP_CONTROL_PORT = int(NETWORK_PORTS["server_udp_control"])


def _require_config_section(raw: object, section_name: str) -> JsonObject:
    if is_json_object(raw):
        return raw
    raise ValueError(f"config section {section_name!r} must be a YAML object")


DEFAULT_CONFIG: JsonObject = {
    "ap": {
        "ssid": "VibeSensor",
        "psk": "",
        "ip": "10.4.0.1/24",
        "channel": 7,
        "ifname": "wlan0",
        "con_name": "VibeSensor-AP",
        "self_heal": {
            "enabled": True,
            "diagnostics_lookback_minutes": 5,
            "min_restart_interval_seconds": 120,
            "allow_disable_resolved_stub_listener": False,
            "state_file": "data/hotspot-self-heal-state.json",
        },
    },
    "server": {"host": "0.0.0.0", "port": 80},
    "udp": {
        "data_listen": f"0.0.0.0:{DEFAULT_UDP_DATA_PORT}",
        "control_listen": f"0.0.0.0:{DEFAULT_UDP_CONTROL_PORT}",
        "data_queue_maxsize": 1024,
    },
    "processing": {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "client_ttl_seconds": 120,
        "accel_scale_g_per_lsb": None,
    },
    "logging": {
        "log_metrics": True,
        "history_db_path": "data/history.db",
        "metrics_log_hz": 4,
        "no_data_timeout_s": 15.0,
        "sensor_model": "ADXL345",
        "persist_history_db": True,
        "shutdown_analysis_timeout_s": 30,
        "app_log_path": "data/app.log",
    },
    "gps": {"gps_enabled": True, "gpsd_host": "127.0.0.1", "gpsd_port": 2947},
    "update": {
        "rollback_dir": "/var/lib/vibesensor/rollback",
    },
}


def documented_default_config() -> JsonObject:
    """Return runtime defaults in the shape documented by config.example.yaml."""
    return deepcopy(DEFAULT_CONFIG)
