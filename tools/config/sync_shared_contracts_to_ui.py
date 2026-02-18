#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "libs" / "shared" / "ts" / "contracts.ts"
DST = ROOT / "apps" / "ui" / "src" / "generated" / "shared_contracts.ts"


def main() -> None:
    DST.parent.mkdir(parents=True, exist_ok=True)
    content = SRC.read_text(encoding="utf-8")
    generated = (
        "// Generated from libs/shared/ts/contracts.ts\n"
        "// Do not edit manually; run tools/config/sync_shared_contracts_to_ui.py\n\n"
        + content
    )
    DST.write_text(generated, encoding="utf-8")
    print(f"Synced {SRC.relative_to(ROOT)} -> {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
