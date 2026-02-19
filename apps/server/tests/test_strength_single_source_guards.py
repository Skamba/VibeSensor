from __future__ import annotations

import ast
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


def _has_log10_call(text: str) -> bool:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "log10":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "log10":
            return True
    return False


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
    repo_root = Path(__file__).resolve().parents[3]
    server_root = repo_root / "apps" / "server" / "vibesensor"
    core_vibration_math = (
        repo_root / "libs" / "core" / "python" / "vibesensor_core" / "vibration_strength.py"
    )

    for path in sorted(server_root.rglob("*.py")):
        text = _read(path)
        assert not _has_log10_call(text), f"Unexpected log10 use in {path}"

    assert core_vibration_math.exists(), (
        f"Missing canonical core math module: {core_vibration_math}"
    )
    assert _has_log10_call(_read(core_vibration_math))


def test_server_no_local_vibration_strength_module() -> None:
    path = Path(__file__).resolve().parents[1] / "vibesensor" / "analysis" / "vibration_strength.py"
    assert not path.exists(), f"Server-local vibration strength module should be removed: {path}"


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
