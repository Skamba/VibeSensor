from __future__ import annotations

import json
import os
from pathlib import Path

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


def _load_json_object(name: str) -> dict[str, object]:
    path = _CONTRACTS_DIR / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a top-level JSON object")
    return payload


def _load_string_map(name: str) -> dict[str, str]:
    payload = _load_json_object(name)
    result: dict[str, str] = {}
    path = _CONTRACTS_DIR / name
    for key, value in payload.items():
        if value is None:
            raise ValueError(f"{path} contains null for key {key!r}; expected a string value")
        result[str(key)] = str(value)
    return result


def _load_int_map(name: str) -> dict[str, int]:
    payload = _load_json_object(name)
    result: dict[str, int] = {}
    path = _CONTRACTS_DIR / name
    for key, value in payload.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{path} contains non-integer value for key {key!r}: {value!r}"
            ) from exc
    return result


METRIC_FIELDS: dict[str, str] = _load_string_map("metrics_fields.json")
REPORT_FIELDS: dict[str, str] = _load_string_map("report_fields.json")
NETWORK_PORTS: dict[str, int] = _load_int_map("network_ports.json")

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
