from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pi"))

from vibesensor.config import AppConfig, load_config  # noqa: E402


def summarize(cfg: AppConfig) -> dict[str, object]:
    return {
        "config_path": str(cfg.config_path),
        "server": {"host": cfg.server.host, "port": cfg.server.port},
        "udp": {
            "data_host": cfg.udp.data_host,
            "data_port": cfg.udp.data_port,
            "control_host": cfg.udp.control_host,
            "control_port": cfg.udp.control_port,
        },
        "processing": {
            "sample_rate_hz": cfg.processing.sample_rate_hz,
            "ui_push_hz": cfg.processing.ui_push_hz,
            "ui_heavy_push_hz": cfg.processing.ui_heavy_push_hz,
        },
        "paths": {
            "metrics_log_path": str(cfg.logging.metrics_log_path),
            "clients_json_path": str(cfg.clients_json_path),
        },
        "logging": {
            "sensor_model": cfg.logging.sensor_model,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and print resolved VibeSensor config")
    parser.add_argument("config", type=Path, help="Path to config YAML")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    print(json.dumps(summarize(cfg), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
