"""Export the HTTP API OpenAPI schema for frontend contract generation.

Usage:
    python -m vibesensor.cli.http_api_schema_export [--out PATH]

Prints to stdout unless ``--out`` is given. ``make sync-contracts`` feeds this to the
UI TypeScript codegen; the schema itself is not committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from vibesensor.adapters.http import create_router
from vibesensor.adapters.http.dependencies import (
    HealthDeps,
    HistoryDeps,
    LiveDeps,
    RouterDeps,
    SettingsDeps,
    UpdateDeps,
)


def _build_openapi_app() -> FastAPI:
    placeholder: Any = object()
    settings = SettingsDeps(
        car_settings=placeholder,
        analysis_settings=placeholder,
        ui_preferences=placeholder,
        speed_source_service=placeholder,
        speed_status_service=placeholder,
        obd_admin_service=placeholder,
    )
    services = RouterDeps(
        health=HealthDeps(
            processing_loop_state=placeholder,
            health_state=placeholder,
            processor=placeholder,
            registry=placeholder,
            run_recorder=placeholder,
            ingest_diagnostics=placeholder,
        ),
        settings=settings,
        live=LiveDeps(
            registry=placeholder,
            control_plane=placeholder,
            sensor_metadata_store=placeholder,
            processor=placeholder,
            run_recorder=placeholder,
            ws_hub=placeholder,
        ),
        history=HistoryDeps(
            run_service=placeholder,
            report_service=placeholder,
            export_service=placeholder,
        ),
        updates=UpdateDeps(
            update_manager=placeholder,
            esp_flash_manager=placeholder,
        ),
    )
    app = FastAPI(title="VibeSensor HTTP API")
    app.include_router(create_router(services))
    return app


def export_schema(out_path: Path | None = None) -> str:
    """Return the HTTP API OpenAPI schema and optionally write it to *out_path*."""
    schema = _build_openapi_app().openapi()
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    """CLI entry point, run as ``python -m vibesensor.cli.http_api_schema_export``."""
    parser = argparse.ArgumentParser(description="Export HTTP API OpenAPI schema")
    parser.add_argument("--out", type=Path, default=None, help="Output file path")
    args = parser.parse_args()
    text = export_schema(args.out)
    if args.out is None:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
