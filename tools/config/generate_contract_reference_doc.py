"""Generate or check the checked-in contract reference markdown from backend sources."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vibesensor.cli.contract_reference_doc import render_contract_reference_markdown

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "docs" / "protocol.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate or check the checked-in contract reference markdown."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if docs/protocol.md differs from the generated contract reference.",
    )
    args = parser.parse_args()

    generated = render_contract_reference_markdown()
    if args.check:
        if not OUTPUT_PATH.exists():
            print(
                f"FAIL: {OUTPUT_PATH.relative_to(ROOT)} does not exist. Run `make sync-contracts` first.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        committed = OUTPUT_PATH.read_text(encoding="utf-8")
        if committed != generated:
            print(
                "FAIL: docs/protocol.md is out of date.\n"
                "Run `make sync-contracts` and commit the result.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"OK: {OUTPUT_PATH.relative_to(ROOT)} is up to date.")
        return

    OUTPUT_PATH.write_text(generated, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
