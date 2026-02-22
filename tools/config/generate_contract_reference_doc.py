from __future__ import annotations

from pathlib import Path

from vibesensor.contract_reference_doc import render_contract_reference_markdown


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    out_path = ROOT / "docs" / "protocol.md"
    out_path.write_text(render_contract_reference_markdown(), encoding="utf-8")
    print(f"Wrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()