from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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


def _load_json(name: str) -> dict[str, Any]:
    return json.loads((_contracts_dir() / name).read_text(encoding="utf-8"))


METRIC_FIELDS: dict[str, str] = _load_json("metrics_fields.json")
REPORT_FIELDS: dict[str, str] = _load_json("report_fields.json")
NETWORK_PORTS: dict[str, int] = _load_json("network_ports.json")
