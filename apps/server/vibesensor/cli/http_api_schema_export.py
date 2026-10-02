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
from dataclasses import fields
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from vibesensor.web.router import WebServices, create_router


def _build_openapi_app() -> FastAPI:
    placeholder: Any = object()
    services = WebServices(**{field.name: placeholder for field in fields(WebServices)})
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
