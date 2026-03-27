"""Generate the checked-in contract reference markdown from backend sources."""

from __future__ import annotations

from pathlib import Path

from vibesensor.cli.contract_reference_doc import render_contract_reference_markdown

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "docs" / "protocol.md"


def main() -> None:
    OUTPUT_PATH.write_text(render_contract_reference_markdown(), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
