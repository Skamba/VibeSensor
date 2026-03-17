"""Verify import boundary rules across layers.

Rules enforced:
1. Service modules must not import FastAPI's HTTPException.
2. ``domain/`` must not import from ``adapters/``, ``infra/``, ``shared/types/``, ``use_cases/``.
3. ``shared/types/backend_types.py`` must not import from ``infra/config/``.
4. Boundary types must not have factory methods that construct domain objects.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _paths import SERVER_ROOT


def _imports_from_analysis(path: Path) -> list[str]:
    """Return import lines that reference ``vibesensor.use_cases.diagnostics`` or ``.analysis``."""
    source = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("vibesensor.use_cases.diagnostics"):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Relative import from .analysis or ..analysis
            if module == "analysis" or module.startswith("analysis."):
                violations.append(f"from .{module} import ...")
            # Absolute import
            if module.startswith("vibesensor.use_cases.diagnostics"):
                violations.append(f"from {module} import ...")
    return violations


def test_history_services_do_not_import_httpexception() -> None:
    """Service-layer modules must not import FastAPI's HTTPException.

    Only HTTP adapter modules should import or raise HTTPException.
    Domain exceptions from ``vibesensor.shared.exceptions`` should be used instead,
    and the ``adapters/http/_helpers.py::domain_errors_to_http()`` context manager
    translates them at the route boundary.
    """
    service_modules = [
        SERVER_ROOT / "vibesensor" / "use_cases" / "history" / "helpers.py",
        SERVER_ROOT / "vibesensor" / "use_cases" / "history" / "runs.py",
        SERVER_ROOT / "vibesensor" / "use_cases" / "history" / "reports.py",
        SERVER_ROOT / "vibesensor" / "use_cases" / "history" / "exports.py",
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


# ── Domain must not import from outer layers ─────────────────────────────

_FORBIDDEN_DOMAIN_IMPORTS = (
    "vibesensor.adapters",
    "vibesensor.infra",
    "vibesensor.shared.types",
    "vibesensor.use_cases",
)


def _collect_domain_import_violations() -> list[str]:
    """Scan all domain/ .py files for imports from outer layers."""
    domain_dir = SERVER_ROOT / "vibesensor" / "domain"
    violations: list[str] = []
    for py_file in sorted(domain_dir.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in _FORBIDDEN_DOMAIN_IMPORTS:
                        if alias.name.startswith(prefix):
                            violations.append(f"{py_file.name}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in _FORBIDDEN_DOMAIN_IMPORTS:
                    if module.startswith(prefix):
                        violations.append(f"{py_file.name}:{node.lineno}: from {module} import ...")
    return violations


def test_domain_does_not_import_from_outer_layers() -> None:
    """domain/ must not import from adapters, infra, shared/types, or use_cases."""
    violations = _collect_domain_import_violations()
    assert not violations, "Domain modules must not import from outer layers:\n  " + "\n  ".join(
        violations
    )


# ── shared/types must not import from infra ──────────────────────────────


def test_shared_types_does_not_import_from_infra() -> None:
    """shared/types/ must not import from infra/ — wrong dependency direction."""
    path = SERVER_ROOT / "vibesensor" / "shared" / "types" / "backend_types.py"
    source = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("vibesensor.infra"):
                violations.append(f"L{node.lineno}: from {module} import ...")
    assert not violations, "backend_types.py must not import from infra/config/:\n  " + "\n  ".join(
        violations
    )


# ── Boundary types must not have domain factory methods ──────────────────


def test_boundary_types_no_domain_factory_methods() -> None:
    """Boundary types (CarConfig, SensorConfig) should not construct domain objects directly."""
    path = SERVER_ROOT / "vibesensor" / "shared" / "types" / "backend_types.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    factory_methods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "to_car",
            "to_sensor",
            "to_car_snapshot",
        ):
            factory_methods.append(f"L{node.lineno}: {node.name}()")
    assert not factory_methods, (
        "Boundary types must not have domain factory methods — "
        "use boundary decoders instead:\n  " + "\n  ".join(factory_methods)
    )
