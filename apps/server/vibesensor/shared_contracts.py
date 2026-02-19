from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _contracts_dir() -> Path:
    cursor = Path(__file__).resolve()
    for candidate in [cursor, *cursor.parents]:
        contracts = candidate / "libs" / "shared" / "contracts"
        if contracts.is_dir():
            return contracts
    raise FileNotFoundError("Could not find libs/shared/contracts from server package path")


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((_contracts_dir() / name).read_text(encoding="utf-8"))


METRIC_FIELDS: dict[str, str] = _load_json("metrics_fields.json")
REPORT_FIELDS: dict[str, str] = _load_json("report_fields.json")


def validate_ingestion_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "payload must be an object"
    client_name = payload.get("client_name")
    if not isinstance(client_name, str) or not client_name.strip():
        return False, "client_name is required"
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        return False, "samples must be a non-empty array"
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            return False, f"samples[{index}] must be an object"
        for axis in ("x_g", "y_g", "z_g"):
            value = sample.get(axis)
            if not isinstance(value, (int, float)):
                return False, f"samples[{index}].{axis} must be numeric"
    return True, "ok"


__all__ = ["METRIC_FIELDS", "REPORT_FIELDS", "validate_ingestion_payload"]
