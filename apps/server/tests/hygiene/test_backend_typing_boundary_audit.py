from __future__ import annotations

import re
import tomllib

from _paths import SERVER_ROOT

TARGETED_MYPY_FILES = {
    "vibesensor/api_models.py",
    "vibesensor/backend_types.py",
    "vibesensor/config.py",
    "vibesensor/gps_speed.py",
    "vibesensor/history_services",
    "vibesensor/json_types.py",
    "vibesensor/payload_types.py",
    "vibesensor/registry.py",
    "vibesensor/run_context.py",
    "vibesensor/settings_store.py",
}

_TARGETED_MYPY_FILES_FOR_SCAN = sorted(
    f for f in TARGETED_MYPY_FILES if f != "vibesensor/json_types.py"
)

TARGETED_WEAK_TYPING_FILES: list = []
for _path_str in _TARGETED_MYPY_FILES_FOR_SCAN:
    _p = SERVER_ROOT / _path_str
    if _p.is_dir():
        TARGETED_WEAK_TYPING_FILES.extend(sorted(_p.rglob("*.py")))
    else:
        TARGETED_WEAK_TYPING_FILES.append(_p)

WEAK_TYPING_PATTERNS = [
    re.compile(r"\bAny\b"),
    re.compile(r"cast\(Any"),
    re.compile(r"dict\[str, Any\]"),
    re.compile(r"Mapping\[str, Any\]"),
    re.compile(r"list\[Any\]"),
]


def test_backend_typecheck_scope_includes_hardened_boundary_modules() -> None:
    pyproject = tomllib.loads((SERVER_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy_files = set(pyproject["tool"]["mypy"]["files"])
    missing = sorted(TARGETED_MYPY_FILES - mypy_files)
    assert missing == []


def test_hardened_backend_boundary_modules_avoid_any_escape_hatches() -> None:
    violations: list[str] = []
    for path in TARGETED_WEAK_TYPING_FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in WEAK_TYPING_PATTERNS:
            if pattern.search(text):
                violations.append(f"{path.relative_to(SERVER_ROOT)} matched {pattern.pattern!r}")
    assert violations == []
