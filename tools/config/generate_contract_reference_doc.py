from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server"))
sys.path.insert(0, str(ROOT / "libs" / "shared" / "python"))


def main() -> None:
    from vibesensor.contract_reference_doc import render_contract_reference_markdown

    out_path = ROOT / "docs" / "protocol.md"
    out_path.write_text(render_contract_reference_markdown(), encoding="utf-8")
    print(f"Wrote {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()