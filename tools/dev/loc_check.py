#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".cpp", ".h", ".hpp", ".sh"}
SKIP_PARTS = {
    ".git",
    ".cache",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    ".pio",
    "artifacts",
}
LEGACY_OVER_600_ALLOWLIST = {
    Path("apps/server/tests/test_history_simulated_runs.py"),
    Path("apps/server/vibesensor/car_library.py"),
    Path("apps/server/vibesensor/hotspot_self_heal.py"),
    Path("apps/server/vibesensor/report_analysis.py"),
    Path("apps/server/vibesensor/report_i18n.py"),
    Path("apps/server/vibesensor/report_pdf.py"),
    Path("apps/simulator/sim_sender.py"),
    Path("apps/ui/src/main.ts"),
}


def _line_count(path: Path) -> int:
    return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))


def _source_files() -> list[Path]:
    files = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    out: list[Path] = []
    for rel in files:
        path = ROOT / rel
        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        if set(path.parts) & SKIP_PARTS:
            continue
        if path.is_file():
            out.append(path)
    return out


def main() -> int:
    rows = sorted(((_line_count(path), path.relative_to(ROOT)) for path in _source_files()), reverse=True)
    over_600 = [(n, path) for n, path in rows if n > 600]
    unexpected_over_600 = [(n, path) for n, path in over_600 if path not in LEGACY_OVER_600_ALLOWLIST]
    over_450 = [(n, path) for n, path in rows if n > 450][:10]

    print(f"Files >600 LOC: {len(over_600)}")
    for n, path in over_600:
        print(f"  {n:4d}  {path}")

    print("Top 10 files >450 LOC:")
    for n, path in over_450:
        print(f"  {n:4d}  {path}")

    if unexpected_over_600:
        print("Unexpected files >600 LOC (fail):")
        for n, path in unexpected_over_600:
            print(f"  {n:4d}  {path}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
