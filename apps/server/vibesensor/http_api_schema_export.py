"""Export the HTTP API OpenAPI schema for frontend contract generation.

Usage:
    python -m vibesensor.http_api_schema_export [--out PATH]

Default output: apps/ui/src/contracts/http_api_schema.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI

from .routes import create_router

_DEFAULT_OUT = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "ui"
    / "src"
    / "contracts"
    / "http_api_schema.json"
)


def _build_openapi_app() -> FastAPI:
    placeholder = object()
    services = SimpleNamespace(
        ingress=SimpleNamespace(
            processor=placeholder,
            registry=placeholder,
            control_plane=placeholder,
        ),
        settings=SimpleNamespace(
            settings_store=placeholder,
            gps_monitor=placeholder,
            analysis_settings=placeholder,
            apply_car_settings=placeholder,
            apply_speed_source_settings=placeholder,
        ),
        metrics_logger=placeholder,
        persistence=SimpleNamespace(
            history_db=placeholder,
            run_service=placeholder,
            report_service=placeholder,
            export_service=placeholder,
        ),
        websocket=SimpleNamespace(hub=placeholder),
        update_manager=placeholder,
        esp_flash_manager=placeholder,
        processing=SimpleNamespace(state=placeholder, health_state=placeholder),
    )
    app = FastAPI(title="VibeSensor HTTP API")
    app.include_router(create_router(services))  # type: ignore[arg-type]
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
                "Run 'python -m vibesensor.http_api_schema_export' and commit the result.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"OK: {args.out} is up to date.")
        return

    export_schema(args.out)
    print(f"Schema written to {args.out}")


if __name__ == "__main__":
    main()
