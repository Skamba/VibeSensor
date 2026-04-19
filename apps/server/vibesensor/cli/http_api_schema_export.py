"""Export the HTTP API OpenAPI schema for frontend contract generation.

Usage:
    python -m vibesensor.cli.http_api_schema_export [--out PATH]

Default output: apps/ui/src/contracts/http_api_schema.json
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

_DEFAULT_OUT = (
    Path(__file__).resolve().parents[4]
    / "apps"
    / "ui"
    / "src"
    / "contracts"
    / "http_api_schema.json"
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
    """Entry point for the ``vibesensor-http-api-schema-export`` CLI tool."""
    parser = argparse.ArgumentParser(description="Export HTTP API OpenAPI schema")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Output file path")
    parser.add_argument("--check", action="store_true", help="Fail if committed schema differs")
    args = parser.parse_args()

    generated = export_schema()
    if args.check:
        if not args.out.exists():
            print(f"FAIL: {args.out} does not exist. Run without --check first.", file=sys.stderr)
            raise SystemExit(1)
        committed = args.out.read_text(encoding="utf-8")
        if committed != generated:
            print(
                f"FAIL: {args.out} is out of date.\n"
                "Run `make sync-contracts` and commit the results.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"OK: {args.out} is up to date.")
        return

    export_schema(args.out)
    print(f"Schema written to {args.out}")


if __name__ == "__main__":
    main()
