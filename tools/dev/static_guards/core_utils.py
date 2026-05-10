"""Shared AST, import, and path utilities for backend static guards."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

SERVER_ROOT = REPO_ROOT / "apps" / "server"

UI_SRC_DIR = REPO_ROOT / "apps" / "ui" / "src"

VIBESENSOR_DIR = SERVER_ROOT / "vibesensor"

TESTS_DIR = SERVER_ROOT / "tests"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_python(path: Path) -> ast.AST | None:
    try:
        return ast.parse(_read_text(path), filename=str(path))
    except SyntaxError:
        return None


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def _paths_from_roots(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(_python_files(root))
    return files


def _path_absence_check(path: Path, message: str) -> Callable[[], list[str]]:
    def check() -> list[str]:
        return [message] if path.exists() else []

    return check


def _import_prefix_check(
    *,
    paths_provider: Callable[[], list[Path]],
    prefixes: tuple[str, ...],
    failure_template: str,
) -> Callable[[], list[str]]:
    def check() -> list[str]:
        failures: list[str] = []
        for path in paths_provider():
            violations = _imports_from_prefixes(path, prefixes)
            if violations:
                failures.append(
                    failure_template.format(
                        path=path.relative_to(REPO_ROOT),
                        violations="\n".join(violations),
                    )
                )
        return failures

    return check


def _legacy_module_import_check(
    *,
    legacy_path: Path,
    legacy_path_message: str,
    scan_roots: tuple[Path, ...],
    direct_module: str,
    direct_module_message: str,
    reexport_module: str | None = None,
    reexport_name: str | None = None,
    reexport_message: str | None = None,
) -> Callable[[], list[str]]:
    def check() -> list[str]:
        violations: list[str] = []
        if legacy_path.exists():
            violations.append(legacy_path_message)
        for root in scan_roots:
            for path in _python_files(root):
                if path == legacy_path:
                    continue
                for lineno, module, names, level in _scan_imports(path):
                    if level > 0:
                        continue
                    if module == direct_module:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{lineno}: {direct_module_message}"
                        )
                    if (
                        reexport_module is not None
                        and reexport_name is not None
                        and reexport_message is not None
                        and module == reexport_module
                        and reexport_name in names
                    ):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{lineno}: {reexport_message}"
                        )
        return violations

    return check


def _has_log10_call(path: Path) -> bool:
    tree = _parse_python(path)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "log10":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "log10":
            return True
    return False


def _scan_imports(path: Path) -> list[tuple[int, str, tuple[str, ...], int]]:
    tree = _parse_python(path)
    if tree is None:
        return []
    imports: list[tuple[int, str, tuple[str, ...], int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                (node.lineno, alias.name, (alias.name,), 0) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            imports.append(
                (
                    node.lineno,
                    node.module or "",
                    tuple(alias.name for alias in node.names),
                    node.level or 0,
                )
            )
    return imports


def _attribute_access_lines(path: Path, attr_name: str) -> list[int]:
    tree = _parse_python(path)
    if tree is None:
        return []
    return sorted(
        {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == attr_name
        }
    )


def _is_inside_function(tree: ast.AST, target: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if child is target:
                    return True
    return False


def _imports_from_analysis(path: Path) -> list[str]:
    violations: list[str] = []
    for lineno, module, names, level in _scan_imports(path):
        if level > 0 and (module == "analysis" or module.startswith("analysis.")):
            violations.append(f"line {lineno}: from .{module} import ...")
        if module.startswith("vibesensor.use_cases.diagnostics"):
            violations.append(f"line {lineno}: from {module} import ...")
        for name in names:
            if name.startswith("vibesensor.use_cases.diagnostics"):
                violations.append(f"line {lineno}: import {name}")
    return violations


def _imports_from_prefixes(path: Path, prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for lineno, module, names, _level in _scan_imports(path):
        if any(module.startswith(prefix) for prefix in prefixes):
            violations.append(f"line {lineno}: from {module} import ...")
        for name in names:
            if any(name.startswith(prefix) for prefix in prefixes):
                violations.append(f"line {lineno}: import {name}")
    return violations


def _find_enclosing_function(tree: ast.AST, target_lineno: int) -> str | None:
    best: str | None = None
    best_line = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or float("inf")
            if node.lineno <= target_lineno <= end and node.lineno >= best_line:
                best = node.name
                best_line = node.lineno
    return best


__all__ = [name for name in globals() if not name.startswith("__")]
