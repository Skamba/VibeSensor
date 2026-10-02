"""Export the JSON Schema for LiveWsPayload to a file.

Usage:
    python -m vibesensor.cli.ws_schema_export [--out PATH]

Prints to stdout unless ``--out`` is given. ``make sync-contracts`` feeds this to the
UI TypeScript codegen; the schema itself is not committed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def export_schema(out_path: Path | None = None) -> str:
    """Return the JSON Schema string and optionally write it to *out_path*."""
    from pydantic import TypeAdapter

    from vibesensor.live.payload_types import LiveWsPayload

    schema = TypeAdapter(LiveWsPayload).json_schema()
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    """CLI entry point, run as ``python -m vibesensor.cli.ws_schema_export``."""
    parser = argparse.ArgumentParser(description="Export WS payload JSON Schema")
    parser.add_argument("--out", type=Path, default=None, help="Output file path")
    args = parser.parse_args()
    text = export_schema(args.out)
    if args.out is None:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
