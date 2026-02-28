"""Export the JSON Schema for LiveWsPayload to a file.

Usage:
    python -m vibesensor.ws_schema_export [--out PATH]

Default output: apps/ui/src/contracts/ws_payload_schema.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def export_schema(out_path: Path | None = None) -> str:
    """Return the JSON Schema string and optionally write it to *out_path*."""
    from vibesensor.ws_models import LiveWsPayload

    schema = LiveWsPayload.model_json_schema()
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text)
    return text


def main() -> None:
    default_out = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "ui"
        / "src"
        / "contracts"
        / "ws_payload_schema.json"
    )
    parser = argparse.ArgumentParser(description="Export WS payload JSON Schema")
    parser.add_argument("--out", type=Path, default=default_out, help="Output file path")
    parser.add_argument("--check", action="store_true", help="Fail if committed schema differs")
    args = parser.parse_args()

    generated = export_schema()
    if args.check:
        if not args.out.exists():
            print(f"FAIL: {args.out} does not exist. Run without --check first.", file=sys.stderr)
            raise SystemExit(1)
        committed = args.out.read_text()
        if committed != generated:
            print(
                f"FAIL: {args.out} is out of date.\n"
                "Run 'python -m vibesensor.ws_schema_export' and commit the result.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"OK: {args.out} is up to date.")
    else:
        export_schema(args.out)
        print(f"Schema written to {args.out}")


if __name__ == "__main__":
    main()
