"""Runtime defaults for application configuration."""

from __future__ import annotations

from copy import deepcopy

from vibesensor.shared.types.json_types import JsonObject

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
            "state_file": "data/hotspot-self-heal-state.json",
        },
    },
    "server": {"host": "0.0.0.0", "port": 80},
    "udp": {
        "data_host": "0.0.0.0",
        "data_port": 9000,
        "control_host": "0.0.0.0",
        "control_port": 9001,
        "data_queue_maxsize": 1024,
    },
    "processing": {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "client_live_ttl_seconds": 10,
        "client_ttl_seconds": 120,
        "accel_scale_g_per_lsb": None,
    },
    "logging": {
        "history_db_path": "data/history.db",
        "metrics_log_hz": 4,
        "no_data_timeout_s": 15.0,
        "persist_history_db": True,
        "run_retention_days": 7,
        "shutdown_analysis_timeout_s": 30,
        "app_log_path": "data/app.log",
    },
    "gps": {"gps_enabled": True, "gpsd_host": "127.0.0.1", "gpsd_port": 2947},
    "update": {
        "rollback_dir": "/var/lib/vibesensor/rollback",
    },
    "tracing": {
        "enabled": False,
        "output_path": "data/traces.jsonl",
    },
}


__all__ = ["DEFAULT_CONFIG", "documented_default_config"]


def documented_default_config() -> JsonObject:
    """Return runtime defaults used by config loading and preflight checks."""
    return deepcopy(DEFAULT_CONFIG)
