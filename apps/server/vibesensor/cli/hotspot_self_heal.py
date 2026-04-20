"""CLI entry point for the hotspot self-heal watchdog."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from vibesensor.adapters.hotspot.self_heal import run_self_heal
from vibesensor.app.config_loader import load_config


def main() -> None:
    """Run the hotspot self-heal watchdog from the configured AP settings."""
    parser = argparse.ArgumentParser(description="VibeSensor hotspot health check and self-healing")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/vibesensor/config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--mode",
        choices=["check-heal", "diagnostics"],
        default="check-heal",
        help="check-heal: health check + remediation, diagnostics: collect diagnostics only",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    diagnostics_only = args.mode == "diagnostics"
    raise SystemExit(run_self_heal(cfg.ap, cfg.ap.self_heal, diagnostics_only=diagnostics_only))
