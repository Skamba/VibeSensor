#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".cpp", ".h", ".sh"}
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


def iter_source_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTS:
            continue
        if set(path.parts) & SKIP_PARTS:
            continue
        out.append(path)
    return out


def line_count(path: Path) -> int:
    return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))


def check_file_sizes() -> tuple[bool, list[str]]:
    large: list[str] = []
    total = 0
    for path in iter_source_files():
        total += 1
        n = line_count(path)
        if n > 600:
            large.append(f"{path.relative_to(ROOT)} ({n} lines)")
    ratio_ok = (total - len(large)) / max(1, total) >= 0.9
    ok = ratio_ok
    msgs = [f"source_files={total}", f"over_600={len(large)}", f"within_600_ratio={(total-len(large))/max(1,total):.3f}"]
    msgs.extend(large[:30])
    return ok, msgs


def check_entrypoints() -> tuple[bool, list[str]]:
    required = [
        ROOT / "apps/server/vibesensor/app.py",
        ROOT / "apps/ui/src/main.ts",
        ROOT / "firmware/esp/src/main.cpp",
        ROOT / "infra/pi-image/pi-gen/build.sh",
        ROOT / "docs/ai/repo-map.md",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    return not missing, ([] if not missing else [f"missing: {m}" for m in missing])


def check_core_purity() -> tuple[bool, list[str]]:
    forbidden = [
        r"\bfastapi\b",
        r"\bflask\b",
        r"\bsubprocess\b",
        r"\bsocket\b",
        r"\brequests\b",
        r"\burllib\b",
        r"\bpathlib\b",
        r"\bos\b",
        r"\bsqlite3\b",
        r"\bpsycopg\b",
    ]
    bad: list[str] = []
    core_dir = ROOT / "libs/core"
    if not core_dir.exists():
        return False, ["missing libs/core"]
    for path in core_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in forbidden:
            if re.search(pat, text):
                bad.append(f"{path.relative_to(ROOT)} matches {pat}")
                break
    return not bad, bad


def check_contracts() -> tuple[bool, list[str]]:
    needed = [
        ROOT / "libs/shared/contracts/ingestion_payload.schema.json",
        ROOT / "libs/shared/contracts/metrics_fields.json",
        ROOT / "libs/shared/contracts/report_fields.json",
    ]
    missing = [str(p.relative_to(ROOT)) for p in needed if not p.exists()]
    uses: list[str] = []
    server_ref = ROOT / "apps/server/vibesensor/shared_contracts.py"
    ui_ref = ROOT / "apps/ui/src/main.ts"
    fw_ref = ROOT / "firmware/esp/include/vibesensor_contracts.h"
    if server_ref.exists() and "METRIC_FIELDS" in server_ref.read_text(encoding="utf-8", errors="ignore"):
        uses.append("server_shared_contracts")
    if ui_ref.exists() and "METRIC_FIELDS" in ui_ref.read_text(encoding="utf-8", errors="ignore"):
        uses.append("ui_metric_fields")
    if fw_ref.exists() and "VS_FIELD_VIBRATION_STRENGTH_DB" in fw_ref.read_text(encoding="utf-8", errors="ignore"):
        uses.append("firmware_contract_reference")
    ok = not missing and len(uses) == 3
    msgs = [f"uses={','.join(uses) if uses else 'none'}"]
    msgs.extend([f"missing: {m}" for m in missing])
    return ok, msgs


def check_tooling_docs_noise() -> tuple[bool, list[str]]:
    msgs: list[str] = []
    ok = True
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8", errors="ignore") if (ROOT / "Makefile").exists() else ""
    for target in ["format:", "lint:", "test:", "smoke:"]:
        if target not in makefile:
            ok = False
            msgs.append(f"missing make target {target}")
    for doc in [ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "CLAUDE.md"]:
        if not doc.exists():
            ok = False
            msgs.append(f"missing {doc.relative_to(ROOT)}")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore") if (ROOT / ".gitignore").exists() else ""
    for required in ["artifacts", "apps/ui/node_modules", "apps/ui/dist", "infra/pi-image/pi-gen/.cache"]:
        if required not in gitignore:
            ok = False
            msgs.append(f".gitignore missing pattern containing '{required}'")
    if not (ROOT / "artifacts").exists():
        ok = False
        msgs.append("missing artifacts/ directory")
    return ok, msgs


def main() -> int:
    checks = {
        "file_sizes": check_file_sizes(),
        "entrypoints": check_entrypoints(),
        "core_purity": check_core_purity(),
        "contracts": check_contracts(),
        "tooling_docs_noise": check_tooling_docs_noise(),
    }
    all_ok = True
    for name, (ok, msgs) in checks.items():
        print(f"[{ 'PASS' if ok else 'FAIL' }] {name}")
        for msg in msgs:
            print(f"  - {msg}")
        all_ok &= ok
    (ROOT / "artifacts" / "ai").mkdir(parents=True, exist_ok=True)
    (ROOT / "artifacts" / "ai" / "heuristics_audit.json").write_text(
        json.dumps({k: {"ok": v[0], "messages": v[1]} for k, v in checks.items()}, indent=2),
        encoding="utf-8",
    )
    print("wrote artifacts/ai/heuristics_audit.json")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
