# ruff: noqa: F403,F405
"""Domain and boundary layer architecture guards."""

from __future__ import annotations

import ast

from .core_utils import *


def _check_domain_does_not_import_outer_packages() -> list[str]:
    forbidden = {
        "boundaries",
        "report",
        "routes",
        "history",
        "history_services",
        "history_db",
        "runtime",
        "metrics_log",
    }
    violations: list[str] = []
    for path in _python_files(VIBESENSOR_DIR / "domain"):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level < 1:
                if any(part in node.module.split(".") for part in forbidden):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports from {node.module}"
                    )
    return violations


def _check_boundaries_do_not_import_outer_layers() -> list[str]:
    boundaries_dir = VIBESENSOR_DIR / "shared" / "boundaries"
    forbidden = {
        "report",
        "routes",
        "history",
        "history_services",
        "history_db",
        "runtime",
        "metrics_log",
    }
    violations: list[str] = []
    for path in _python_files(boundaries_dir):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level < 1:
                if any(part in node.module.split(".") for part in forbidden):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports from {node.module}"
                    )
    return violations


def _check_boundaries_do_not_import_analysis() -> list[str]:
    violations: list[str] = []
    for path in _python_files(VIBESENSOR_DIR / "shared" / "boundaries"):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level < 1:
                if node.module == "vibesensor.shared.constants.analysis":
                    continue
                if "analysis" in node.module.split("."):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports from {node.module}"
                    )
    return violations


def _check_signature_confinement() -> list[str]:
    confined_names = {"Signature"}
    forbidden_dirs = [
        VIBESENSOR_DIR / "adapters" / "pdf",
        VIBESENSOR_DIR / "adapters" / "http",
        VIBESENSOR_DIR / "adapters" / "persistence",
        VIBESENSOR_DIR / "adapters" / "websocket",
    ]
    violations: list[str] = []
    for root in forbidden_dirs:
        for path in _python_files(root):
            tree = _parse_python(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name in confined_names:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports {name}"
                        )
    return violations


_CHECK_DOMAIN_IMPORT_DIRECTION = _import_prefix_check(
    paths_provider=lambda: sorted((VIBESENSOR_DIR / "domain").glob("*.py")),
    prefixes=(
        "vibesensor.shared.boundaries",
        "vibesensor.adapters",
        "vibesensor.infra",
    ),
    failure_template="{path} imports inward-forbidden layers:\n{violations}",
)


def _class_field_names(path: Path, class_name: str) -> set[str]:
    tree = _parse_python(path)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        fields: set[str] = set()
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                fields.add(child.target.id)
        return fields
    return set()


def _check_finding_stays_run_scoped() -> list[str]:
    fields = _class_field_names(VIBESENSOR_DIR / "domain" / "finding.py", "Finding")
    cross_run_indicators = {
        "case_id",
        "diagnosis",
        "diagnoses",
        "test_runs",
        "runs",
        "case",
    }
    leaked = sorted(fields & cross_run_indicators)
    if not leaked:
        return []
    return [
        f"vibesensor.domain.Finding must stay run-scoped; remove fields: {', '.join(leaked)}"
    ]


def _check_run_capture_uses_run_id_boundary() -> list[str]:
    path = VIBESENSOR_DIR / "domain" / "run_capture.py"
    fields = _class_field_names(path, "RunCapture")
    failures: list[str] = []
    if "run_id" not in fields:
        failures.append(
            "vibesensor.domain.RunCapture must keep run_id as its lifecycle boundary"
        )
    if "run" in fields:
        failures.append(
            "vibesensor.domain.RunCapture must not hold a mutable Run object"
        )

    tree = _parse_python(path)
    if tree is None:
        return failures
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        names = {alias.name for alias in node.names}
        if "Run" not in names:
            continue
        if node.module == "vibesensor.domain.run" or (
            node.level == 1 and node.module == "run"
        ):
            failures.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports mutable Run"
            )
    return failures


def _check_domain_code_does_not_access_raw_tire_fields() -> list[str]:
    raw_tire_fields = {"tire_width_mm", "tire_aspect_pct", "rim_in"}
    allowed_files = {"snapshots.py", "car.py", "tire_spec.py", "order_reference.py"}
    violations: list[str] = []
    for path in (VIBESENSOR_DIR / "domain").glob("*.py"):
        if path.name in allowed_files:
            continue
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
                if node.attr in raw_tire_fields:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: accesses .{node.attr}"
                    )
    return violations


def _check_domain_and_use_cases_do_not_import_car_config() -> list[str]:
    violations: list[str] = []
    for root_name in ("domain", "use_cases"):
        for path in _python_files(VIBESENSOR_DIR / root_name):
            tree = _parse_python(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "CarConfig" in {alias.name for alias in node.names}:
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports CarConfig"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if "CarConfig" in alias.name:
                            violations.append(
                                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports {alias.name}"
                            )
    return violations


def _check_domain_and_use_cases_do_not_read_raw_aspects_dict_keys() -> list[str]:
    violations: list[str] = []
    allowed_files = {"car.py"}
    for root_name in ("domain", "use_cases"):
        for path in _python_files(VIBESENSOR_DIR / root_name):
            if path.name in allowed_files:
                continue
            tree = _parse_python(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Subscript):
                    if (
                        isinstance(node.slice, ast.Constant)
                        and node.slice.value == "aspects"
                    ):
                        violations.append(
                            f"{path.relative_to(REPO_ROOT)}:{node.lineno}: accesses ['aspects']"
                        )
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "get" and node.args:
                        first_arg = node.args[0]
                        if (
                            isinstance(first_arg, ast.Constant)
                            and first_arg.value == "aspects"
                        ):
                            violations.append(
                                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: accesses .get('aspects')"
                            )
    return violations


def _check_boundary_owns_no_meaning_finding_kind() -> list[str]:
    scan_dirs = [VIBESENSOR_DIR / "adapters", VIBESENSOR_DIR / "shared" / "boundaries"]
    violations: list[str] = []
    for root in scan_dirs:
        for path in _python_files(root):
            tree = _parse_python(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "FindingKind"
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: constructs FindingKind directly"
                    )
    return violations


def _check_boundary_owns_no_meaning_vibration_source() -> list[str]:
    sanctioned: dict[str, set[str]] = {
        "finding.py": {"finding_from_payload"},
        "origin.py": {"_source_from_payload"},
        "mapping.py": {"human_source"},
        "pdf_diagram_render.py": {"_source_color"},
    }
    scan_dirs = [VIBESENSOR_DIR / "adapters", VIBESENSOR_DIR / "shared" / "boundaries"]
    violations: list[str] = []
    for root in scan_dirs:
        for path in _python_files(root):
            tree = _parse_python(path)
            if tree is None:
                continue
            allowed = sanctioned.get(path.name, set())
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "VibrationSource"
                ):
                    continue
                enclosing = _find_enclosing_function(tree, node.lineno)
                if enclosing in allowed:
                    continue
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: constructs VibrationSource in "
                    f"{enclosing or '<module>'}"
                )
    return violations


def _check_run_status_from_domain_only() -> list[str]:
    forbidden_sources = {"history_db", "adapters.persistence.history_db"}
    violations: list[str] = []
    for root in (VIBESENSOR_DIR, TESTS_DIR):
        for path in _python_files(root):
            tree = _parse_python(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module is None:
                    continue
                names = {alias.name for alias in node.names}
                if "RunStatus" not in names:
                    continue
                if any(part in node.module for part in forbidden_sources):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports RunStatus from {node.module}"
                    )
    return violations


def _check_run_lifecycle_only() -> list[str]:
    forbidden_areas = [
        VIBESENSOR_DIR / "use_cases" / "diagnostics",
        VIBESENSOR_DIR / "domain" / "finding.py",
        VIBESENSOR_DIR / "domain" / "test_run.py",
        VIBESENSOR_DIR / "adapters" / "pdf",
    ]
    violations: list[str] = []
    for area in forbidden_areas:
        py_files = (
            _python_files(area) if area.is_dir() else ([area] if area.exists() else [])
        )
        for path in py_files:
            tree = _parse_python(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.module is None:
                    continue
                names = {alias.name for alias in node.names}
                if "Run" not in names:
                    continue
                if (
                    node.module == "vibesensor.domain"
                    or "vibesensor.domain.run" in node.module
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports Run from {node.module}"
                    )
    return violations
