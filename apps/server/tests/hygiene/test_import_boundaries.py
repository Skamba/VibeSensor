"""Verify that root-level analysis bridge modules don't import from analysis/.

``analysis_settings.py`` and ``analysis_persistence.py`` live at the
vibesensor package root specifically to avoid circular dependencies:
``runtime/`` and ``metrics_log/`` depend on them, and they must not
depend on the ``analysis/`` subpackage.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _paths import SERVER_ROOT

_BRIDGE_MODULES = [
    SERVER_ROOT / "vibesensor" / "analysis_settings.py",
    SERVER_ROOT / "vibesensor" / "analysis_persistence.py",
]


def _imports_from_analysis(path: Path) -> list[str]:
    """Return import lines that reference ``vibesensor.analysis`` or ``.analysis``."""
    source = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("vibesensor.analysis"):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Relative import from .analysis or ..analysis
            if module == "analysis" or module.startswith("analysis."):
                violations.append(f"from .{module} import ...")
            # Absolute import
            if module.startswith("vibesensor.analysis"):
                violations.append(f"from {module} import ...")
    return violations


def test_analysis_settings_does_not_import_from_analysis() -> None:
    path = SERVER_ROOT / "vibesensor" / "analysis_settings.py"
    violations = _imports_from_analysis(path)
    assert not violations, (
        f"analysis_settings.py must not import from the analysis/ package "
        f"(circular dependency risk): {violations}"
    )


def test_analysis_persistence_does_not_import_from_analysis() -> None:
    path = SERVER_ROOT / "vibesensor" / "analysis_persistence.py"
    violations = _imports_from_analysis(path)
    assert not violations, (
        f"analysis_persistence.py must not import from the analysis/ package "
        f"(circular dependency risk): {violations}"
    )


def test_history_services_do_not_import_httpexception() -> None:
    """Service-layer modules must not import FastAPI's HTTPException.

    Only ``routes/`` modules should import or raise HTTPException.
    Domain exceptions from ``vibesensor.exceptions`` should be used instead,
    and the ``routes/_helpers.py::domain_errors_to_http()`` context manager
    translates them at the route boundary.
    """
    service_modules = [
        SERVER_ROOT / "vibesensor" / "history_services" / "helpers.py",
        SERVER_ROOT / "vibesensor" / "history_services" / "runs.py",
        SERVER_ROOT / "vibesensor" / "history_services" / "reports.py",
        SERVER_ROOT / "vibesensor" / "history_services" / "exports.py",
    ]
    violations: list[str] = []
    for path in service_modules:
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
                for alias in node.names:
                    if alias.name == "HTTPException":
                        violations.append(f"{path.name}: from fastapi import HTTPException")
    assert not violations, (
        "Service modules must not import HTTPException — use domain exceptions instead: "
        + ", ".join(violations)
    )
