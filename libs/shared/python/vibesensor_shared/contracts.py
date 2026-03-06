from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = [
    "METRIC_FIELDS",
    "NETWORK_PORTS",
    "REPORT_FIELDS",
]


def _contracts_dir() -> Path:
    # Allow explicit override (e.g. Docker containers with non-editable installs)
    env_path = os.environ.get("VIBESENSOR_CONTRACTS_DIR")
    if env_path:
        return Path(env_path)
    # Source tree: contracts/ is a sibling of the python/ package directory
    source_dir = Path(__file__).resolve().parent.parent.parent / "contracts"
    if source_dir.is_dir():
        return source_dir
    raise FileNotFoundError(
        "Cannot locate shared contracts directory. "
        "Set VIBESENSOR_CONTRACTS_DIR or run from the source tree."
    )


# Resolve once at import time instead of per-_load_json call.
_CONTRACTS_DIR: Path = _contracts_dir()


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((_CONTRACTS_DIR / name).read_text(encoding="utf-8"))


METRIC_FIELDS: dict[str, str] = _load_json("metrics_fields.json")
REPORT_FIELDS: dict[str, str] = _load_json("report_fields.json")
NETWORK_PORTS: dict[str, int] = _load_json("network_ports.json")

# Validate that required contract keys exist at import time so misconfigurations
# surface immediately with a descriptive error rather than a cryptic KeyError later.
_REQUIRED_METRIC_KEYS: frozenset[str] = frozenset(
    {"vibration_strength_db", "strength_bucket"}
)
_REQUIRED_REPORT_KEYS: frozenset[str] = frozenset(
    {
        "run_id",
        "timestamp_utc",
        "client_id",
        "client_name",
        "speed_kmh",
        "dominant_freq_hz",
        "vibration_strength_db",
        "strength_bucket",
        "top_peaks",
    }
)
_REQUIRED_PORT_KEYS: frozenset[str] = frozenset(
    {"server_udp_data", "server_udp_control", "firmware_control_port_base"}
)
_missing_metric = _REQUIRED_METRIC_KEYS - METRIC_FIELDS.keys()
if _missing_metric:
    raise KeyError(
        f"metrics_fields.json is missing required keys: {sorted(_missing_metric)}"
    )
_missing_report = _REQUIRED_REPORT_KEYS - REPORT_FIELDS.keys()
if _missing_report:
    raise KeyError(
        f"report_fields.json is missing required keys: {sorted(_missing_report)}"
    )
_missing_ports = _REQUIRED_PORT_KEYS - NETWORK_PORTS.keys()
if _missing_ports:
    raise KeyError(
        f"network_ports.json is missing required keys: {sorted(_missing_ports)}"
    )
