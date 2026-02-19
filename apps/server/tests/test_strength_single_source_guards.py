from __future__ import annotations

import re
from pathlib import Path

import pytest


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _snippet(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    start = max(0, match.start() - 60)
    end = min(len(text), match.end() + 60)
    return text[start:end].replace("\n", " ")


# Lightweight smoke tests: string guards intentionally enforce "no local reimplementation" patterns.
def test_live_diagnostics_avoids_strength_formula_reimplementation() -> None:
    text = _read(Path(__file__).resolve().parents[1] / "vibesensor" / "live_diagnostics.py")
    assert "strength_db_above_floor(" not in text
    assert "compute_floor_rms(" not in text
    assert "compute_band_rms(" not in text


def test_report_analysis_uses_shared_strength_math() -> None:
    text = _read(Path(__file__).resolve().parents[1] / "vibesensor" / "report_analysis.py")
    assert "Math.log10" not in text
    assert "20.0 * log10(" not in text
    assert "bucket_for_strength(" not in text


def test_client_assets_do_not_compute_strength_metrics() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    candidate_dirs = [repo_root / "apps" / "ui" / "dist", repo_root / "apps" / "server" / "public"]
    forbidden_patterns = [
        re.compile(r"Math\.log10\([^)]*/[^)]*\)|log10\([^)]*/[^)]*\)"),
        re.compile(r"detectVibrationEvents"),
        re.compile(
            r"[A-Za-z_$][\w$]*\s*>=\s*[A-Za-z_$][\w$]*\.min_db\s*&&\s*"
            r"[A-Za-z_$][\w$]*\s*<\s*[A-Za-z_$][\w$]*\s*&&\s*"
            r"[A-Za-z_$][\w$]*\s*>=\s*[A-Za-z_$][\w$]*\.min_amp"
        ),
        re.compile(r"x\s*\*\s*x\s*\+\s*y\s*\*\s*y\s*\+\s*z\s*\*\s*z"),
    ]
    scanned = 0
    available_dirs = [d for d in candidate_dirs if d.exists()]
    if not available_dirs:
        pytest.skip(f"No generated UI assets directory found. Checked: {candidate_dirs}")
    for asset_dir in available_dirs:
        for js_file in asset_dir.rglob("*.js"):
            scanned += 1
            text = _read(js_file)
            for pattern in forbidden_patterns:
                snippet = _snippet(text, pattern)
                assert not snippet, f"Forbidden UI metric logic in {js_file}: {snippet}"
    assert scanned > 0, "No generated JS assets found to validate."


def test_strength_metric_definition_is_centralized() -> None:
    root = Path(__file__).resolve().parents[1] / "vibesensor"
    python_files = list(root.rglob("*.py"))
    forbidden_math = re.compile(r"\b(?:math|np)\.log10\(")
    forbidden_bucket_compare = re.compile(
        r"(?:>=|<=|>|<)[^\n]{0,80}(?:\[['\"]min_db['\"]\]|\[['\"]min_amp['\"]\]|\.min_db|\.min_amp)|"
        r"(?:\[['\"]min_db['\"]\]|\[['\"]min_amp['\"]\]|\.min_db|\.min_amp)[^\n]{0,80}(?:>=|<=|>|<)"
    )
    for path in python_files:
        if path.name == "vibration_strength.py":
            continue
        text = _read(path)
        assert forbidden_math.search(text) is None, f"Unexpected log10 use in {path}"
        if path.name in {"strength_bands.py", "diagnostics_shared.py"}:
            continue
        assert forbidden_bucket_compare.search(text) is None, (
            f"Unexpected band thresholds in {path}"
        )


def test_typescript_any_type_budget() -> None:
    """Enforce a budget on `as any` / `: any` usage in TypeScript.

    Only the demo cleanup window hook is allowed.
    """
    repo_root = Path(__file__).resolve().parents[3]
    ui_src = repo_root / "apps" / "ui" / "src"
    any_pattern = re.compile(r"\bas\s+any\b|:\s*any\b")
    # Allowlist: window test hook and large untyped state bags in main.ts
    allowlist = {
        "main.ts": {
            "(window as any).__vibesensorDemoCleanup",
            "const els: any",
            "const state: any",
        },
    }
    violations: list[str] = []
    for ts_file in sorted(ui_src.rglob("*.ts")):
        allowed_set = allowlist.get(ts_file.name, set())
        for i, line in enumerate(ts_file.read_text(encoding="utf-8").splitlines(), 1):
            if any_pattern.search(line):
                stripped = line.strip()
                if any(allowed in stripped for allowed in allowed_set):
                    continue
                violations.append(f"{ts_file.name}:{i}: {stripped}")
    assert not violations, (
        f"Found {len(violations)} unexpected `any` type(s) in TypeScript:\n" + "\n".join(violations)
    )
