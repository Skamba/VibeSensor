from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from _paths import REPO_ROOT, SERVER_ROOT


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


def _assert_no_forbidden_strings(
    pkg_dir: Path,
    forbidden: list[str],
    *,
    suffix: str = "*.py",
) -> None:
    """Assert none of *forbidden* substrings appear in any *suffix* files under *pkg_dir*."""
    for src_file in sorted(pkg_dir.rglob(suffix)):
        text = _read(src_file)
        for needle in forbidden:
            assert needle not in text, f"{needle!r} found in {src_file.name}"


# ---------------------------------------------------------------------------
# Module-level compiled patterns (avoid per-test recompilation)
# ---------------------------------------------------------------------------

_FORBIDDEN_UI_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Math\.log10\([^)]*/[^)]*\)|log10\([^)]*/[^)]*\)"),
    re.compile(r"detectVibrationEvents"),
    re.compile(
        r"[A-Za-z_$][\w$]*\s*>=\s*[A-Za-z_$][\w$]*\.min_db\s*&&\s*"
        r"[A-Za-z_$][\w$]*\s*<\s*[A-Za-z_$][\w$]*\s*&&\s*"
        r"[A-Za-z_$][\w$]*\s*>=\s*[A-Za-z_$][\w$]*\.min_amp",
    ),
    re.compile(r"x\s*\*\s*x\s*\+\s*y\s*\*\s*y\s*\+\s*z\s*\*\s*z"),
)

_ANY_PATTERN: re.Pattern[str] = re.compile(r"\bas\s+any\b|:\s*any\b")


# ---------------------------------------------------------------------------
# Lightweight smoke tests: string guards enforce "no local reimplementation".
# ---------------------------------------------------------------------------


def test_live_diagnostics_avoids_strength_formula_reimplementation() -> None:
    _assert_no_forbidden_strings(
        SERVER_ROOT / "vibesensor" / "live_diagnostics",
        ["strength_db_above_floor(", "compute_floor_rms(", "compute_band_rms("],
    )


def test_report_modules_use_shared_strength_math() -> None:
    _assert_no_forbidden_strings(
        SERVER_ROOT / "vibesensor" / "report",
        ["Math.log10", "20.0 * log10(", "bucket_for_strength("],
    )


def test_client_assets_do_not_compute_strength_metrics() -> None:
    repo_root = REPO_ROOT
    candidate_dirs = [repo_root / "apps" / "ui" / "dist", repo_root / "apps" / "server" / "public"]
    scanned = 0
    available_dirs = [d for d in candidate_dirs if d.exists()]
    if not available_dirs:
        pytest.skip(f"No generated UI assets directory found. Checked: {candidate_dirs}")
    for asset_dir in available_dirs:
        for js_file in asset_dir.rglob("*.js"):
            scanned += 1
            text = _read(js_file)
            for pattern in _FORBIDDEN_UI_PATTERNS:
                snippet = _snippet(text, pattern)
                assert not snippet, f"Forbidden UI metric logic in {js_file}: {snippet}"
    assert scanned > 0, "No generated JS assets found to validate."


def test_strength_metric_definition_is_centralized() -> None:
    repo_root = REPO_ROOT
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
    path = SERVER_ROOT / "vibesensor" / "analysis" / "vibration_strength.py"
    assert not path.exists(), f"Server-local vibration strength module should be removed: {path}"


def test_typescript_any_type_budget() -> None:
    """Enforce a budget on `as any` / `: any` usage in TypeScript.

    Only the demo cleanup window hook is allowed.
    """
    repo_root = REPO_ROOT
    ui_src = repo_root / "apps" / "ui" / "src"
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
            if _ANY_PATTERN.search(line):
                stripped = line.strip()
                if any(allowed in stripped for allowed in allowed_set):
                    continue
                violations.append(f"{ts_file.name}:{i}: {stripped}")
    assert not violations, (
        f"Found {len(violations)} unexpected `any` type(s) in TypeScript:\n" + "\n".join(violations)
    )
