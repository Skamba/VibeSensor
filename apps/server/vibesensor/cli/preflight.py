from __future__ import annotations

import argparse
import json
from pathlib import Path

from vibesensor.app.settings import (
    AppConfig,
    documented_default_config,
    load_config,
    summarize_process_settings,
)
from vibesensor.shared.constants.ui import UI_HEAVY_PUSH_HZ, UI_PUSH_HZ


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
            "ui_push_hz": UI_PUSH_HZ,
            "ui_heavy_push_hz": UI_HEAVY_PUSH_HZ,
        },
        "paths": {
            "history_db_path": str(cfg.logging.history_db_path),
        },
        "process_settings": summarize_process_settings(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and print resolved VibeSensor config")
    parser.add_argument("config", type=Path, nargs="?", help="Path to config YAML")
    parser.add_argument(
        "--dump-defaults",
        action="store_true",
        help="Print the documented default config and exit",
    )
    args = parser.parse_args()
    if args.dump_defaults and args.config is not None:
        parser.error("--dump-defaults and config are mutually exclusive")
    if not args.dump_defaults and args.config is None:
        parser.error("config is required unless --dump-defaults is set")
    return args


def main() -> int:
    args = parse_args()
    if args.dump_defaults:
        print(json.dumps(documented_default_config(), indent=2, sort_keys=True))
        return 0
    cfg = load_config(args.config)
    print(json.dumps(summarize(cfg), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
