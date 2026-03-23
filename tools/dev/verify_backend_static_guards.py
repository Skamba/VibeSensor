"""Explicit backend static guards for architecture and test hygiene.

This script hosts source/AST-based checks that are important to keep, but
which do not belong in normal behavior tests. Run it from ``apps/server`` so
imports of ``vibesensor`` resolve without path hacks.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
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


def _check_backend_tests_do_not_use_source_introspection() -> list[str]:
    patterns = {
        "inspect.getsource(": "inspect.getsource",
        "inspect.getattr_static(": "inspect.getattr_static",
        "inspect.get_annotations(": "inspect.get_annotations",
        "ast.parse(": "ast.parse",
    }
    failures: list[str] = []
    for path in _python_files(TESTS_DIR):
        lines = _read_text(path).splitlines()
        for lineno, line in enumerate(lines, start=1):
            for needle, label in patterns.items():
                if needle in line:
                    rel = path.relative_to(REPO_ROOT)
                    failures.append(
                        f"{rel}:{lineno}: backend tests must not use {label} on source/production code"
                    )
    return failures


_REPORT_DIR = VIBESENSOR_DIR / "adapters" / "pdf"
_REPORT_MODULES = [
    path
    for path in _REPORT_DIR.glob("*.py")
    if path.name not in ("__init__.py", "mapping.py")
]
_LOG10_PATTERN = re.compile(r"\blog10\(")
_JS_STRENGTH_FIELD_MARKERS = (
    "strength_metrics",
    "vibration_strength_db",
    "peak_amp_g",
    "noise_floor_amp_g",
    "top_peaks",
)
_JS_STRENGTH_LOG10_PATTERN = re.compile(r"\b(?:Math\.)?log10\(")


def _is_inside_function(tree: ast.AST, target: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if child is target:
                    return True
    return False


def _check_report_modules_do_not_import_analysis() -> list[str]:
    failures: list[str] = []
    for module_path in _REPORT_MODULES:
        tree = _parse_python(module_path)
        if tree is None:
            continue
        violations: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if _is_inside_function(tree, node):
                continue
            full = node.module
            if node.level > 0:
                if full.startswith("analysis"):
                    violations.append(
                        f"line {node.lineno}: from {'.' * node.level}{full} import ..."
                    )
            elif "analysis" in full.split("."):
                violations.append(f"line {node.lineno}: from {full} import ...")
        if violations:
            failures.append(
                f"{module_path.relative_to(REPO_ROOT)} imports analysis at module level:\n"
                + "\n".join(violations)
            )
    return failures


def _check_report_modules_use_shared_strength_math() -> list[str]:
    failures: list[str] = []
    for module_path in _python_files(_REPORT_DIR):
        text = _read_text(module_path)
        if _has_log10_call(module_path):
            failures.append(
                f"{module_path.relative_to(REPO_ROOT)} must not define vibration dB math locally"
            )
        if "bucket_for_strength(" in text:
            failures.append(
                f"{module_path.relative_to(REPO_ROOT)} must not bucket strength locally"
            )
    return failures


_ANALYSIS_DIR = VIBESENSOR_DIR / "use_cases" / "diagnostics"
_ANALYSIS_MODULES_NO_I18N = [
    path for path in _ANALYSIS_DIR.glob("*.py") if path.name != "__init__.py"
] + [
    path
    for path in (_ANALYSIS_DIR / "report_mapping").glob("*.py")
    if path.name not in ("__init__.py", "pipeline.py")
]


def _check_analysis_modules_do_not_import_i18n() -> list[str]:
    failures: list[str] = []
    for module_path in _ANALYSIS_MODULES_NO_I18N:
        tree = _parse_python(module_path)
        if tree is None:
            continue
        violations: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if "report_i18n" not in node.module:
                continue
            imported_names = {alias.name for alias in node.names}
            if imported_names == {"normalize_lang"}:
                continue
            full = ("." * (node.level or 0)) + node.module
            violations.append(f"line {node.lineno}: from {full} import ...")
        if violations:
            failures.append(
                f"{module_path.relative_to(REPO_ROOT)} imports report_i18n resources:\n"
                + "\n".join(violations)
            )
    return failures


def _ui_source_files() -> list[Path]:
    if not UI_SRC_DIR.exists():
        return []
    files: list[Path] = []
    for suffix in ("*.ts", "*.tsx", "*.js", "*.mjs"):
        files.extend(UI_SRC_DIR.rglob(suffix))
    return sorted(
        path
        for path in files
        if "__tests__" not in path.parts
        and "generated" not in path.parts
        and "contracts" not in path.parts
    )


def _check_ui_code_does_not_compute_strength_metrics() -> list[str]:
    failures: list[str] = []
    for path in _ui_source_files():
        text = _read_text(path)
        if "detectVibrationEvents" in text:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} must not define client-side vibration event detection"
            )
        if _JS_STRENGTH_LOG10_PATTERN.search(text) and any(
            marker in text for marker in _JS_STRENGTH_FIELD_MARKERS
        ):
            failures.append(
                f"{path.relative_to(REPO_ROOT)} must not recompute strength metrics from raw amplitudes"
            )
    return failures


def _check_strength_metric_definition_is_centralized() -> list[str]:
    canonical = VIBESENSOR_DIR / "vibration_strength.py"
    failures: list[str] = []
    for path in _python_files(VIBESENSOR_DIR):
        if path == canonical:
            continue
        if _has_log10_call(path):
            failures.append(
                f"{path.relative_to(REPO_ROOT)} defines log10-based strength math outside vibration_strength.py"
            )
    if not canonical.exists():
        failures.append(
            f"Missing canonical strength math module: {canonical.relative_to(REPO_ROOT)}"
        )
    elif not _has_log10_call(canonical):
        failures.append(
            f"{canonical.relative_to(REPO_ROOT)} must own the canonical log10-based strength math"
        )
    return failures


def _check_server_has_no_local_vibration_strength_module() -> list[str]:
    path = VIBESENSOR_DIR / "use_cases" / "diagnostics" / "vibration_strength.py"
    if path.exists():
        return [
            f"{path.relative_to(REPO_ROOT)} should not exist; use vibesensor/vibration_strength.py"
        ]
    return []


_REPORT_MAPPING_MODULE = VIBESENSOR_DIR / "adapters" / "pdf" / "mapping.py"
_EXTERNAL_MODULES = [
    path
    for path in VIBESENSOR_DIR.rglob("*.py")
    if path.name != "__init__.py"
    and _ANALYSIS_DIR not in path.parents
    and path != _REPORT_MAPPING_MODULE
]


def _analysis_submodule_imports(path: Path) -> list[str]:
    tree = _parse_python(path)
    if tree is None:
        return []
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        mod = node.module
        if node.level > 0:
            if mod.startswith("analysis."):
                violations.append(
                    f"line {node.lineno}: from {'.' * node.level}{mod} import ..."
                )
        else:
            parts = mod.split(".")
            if "analysis" in parts:
                idx = parts.index("analysis")
                if idx + 1 < len(parts):
                    violations.append(f"line {node.lineno}: from {mod} import ...")
    return violations


def _check_external_modules_use_analysis_public_api() -> list[str]:
    failures: list[str] = []
    for module_path in _EXTERNAL_MODULES:
        violations = _analysis_submodule_imports(module_path)
        if violations:
            failures.append(
                f"{module_path.relative_to(REPO_ROOT)} imports analysis submodules directly:\n"
                + "\n".join(violations)
            )
    return failures


def _live_processing_files() -> list[Path]:
    files: list[Path] = []
    processing_dir = VIBESENSOR_DIR / "infra" / "processing"
    if processing_dir.is_dir():
        files.extend(sorted(processing_dir.glob("*.py")))
    else:
        files.append(VIBESENSOR_DIR / "processing.py")
    files.append(VIBESENSOR_DIR / "adapters" / "udp" / "udp_data_rx.py")
    return [path for path in files if path.exists()]


def _check_live_processing_does_not_import_analysis() -> list[str]:
    failures: list[str] = []
    for path in _live_processing_files():
        tree = _parse_python(path)
        if tree is None:
            continue
        violations: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            full = ("." * (node.level or 0)) + node.module
            if "analysis" in node.module.split("."):
                violations.append(f"line {node.lineno}: from {full} import ...")
        if violations:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} imports post-stop analysis:\n"
                + "\n".join(violations)
            )
    return failures


def _check_metrics_log_reads_live_start_under_lock() -> list[str]:
    path = VIBESENSOR_DIR / "use_cases" / "run" / "_recorder_runtime.py"
    source = _read_text(path)
    try:
        lock_idx = source.index("with recorder._lock:")
        live_start_idx = source.index("live_start = recorder._live_start_mono_s")
        build_idx = source.index("build_sample_records")
    except ValueError as exc:
        return [
            f"{path.relative_to(REPO_ROOT)} missing expected recorder lock-order markers: {exc}"
        ]
    if not (lock_idx < live_start_idx < build_idx):
        return [
            f"{path.relative_to(REPO_ROOT)} must read _live_start_mono_s under recorder._lock "
            "before build_sample_records"
        ]
    return []


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


def _check_history_services_do_not_import_httpexception() -> list[str]:
    service_modules = [
        VIBESENSOR_DIR / "use_cases" / "history" / "helpers.py",
        VIBESENSOR_DIR / "use_cases" / "history" / "runs.py",
        VIBESENSOR_DIR / "use_cases" / "history" / "reports.py",
        VIBESENSOR_DIR / "use_cases" / "history" / "exports.py",
    ]
    violations: list[str] = []
    for path in service_modules:
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
                if any(alias.name == "HTTPException" for alias in node.names):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: from fastapi import HTTPException"
                    )
    return violations


def _check_history_report_loader_avoids_analysis_dict_rewrap() -> list[str]:
    path = VIBESENSOR_DIR / "use_cases" / "history" / "report_loader.py"
    tree = _parse_python(path)
    if tree is None:
        return []
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if (
                node.func.id == "dict"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "analysis"
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "HistoryReportRequestLoader must not re-wrap AnalysisSummary with dict(analysis)"
                )
            if (
                node.func.id == "cast"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "AnalysisSummary"
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "HistoryReportRequestLoader must use a typed AnalysisSummary helper instead of cast(...) re-wraps"
                )
    return violations


_ALLOWED_ANALYSIS_SUMMARY_IMPORT_PREFIXES = (
    "shared/boundaries/",
    "adapters/pdf/",
)
_ALLOWED_ANALYSIS_SUMMARY_IMPORT_FILES = frozenset(
    {
        "adapters/analysis_summary.py",
        "use_cases/history/report_loader.py",
        "use_cases/history/report_preparation.py",
    }
)


def _check_analysis_summary_stays_at_boundaries() -> list[str]:
    violations: list[str] = []
    for path in _python_files(VIBESENSOR_DIR):
        rel = str(path.relative_to(VIBESENSOR_DIR))
        if rel in _ALLOWED_ANALYSIS_SUMMARY_IMPORT_FILES or rel.startswith(
            _ALLOWED_ANALYSIS_SUMMARY_IMPORT_PREFIXES
        ):
            continue
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "vibesensor.shared.boundaries.analysis_payload":
                continue
            if any(alias.name == "AnalysisSummary" for alias in node.names):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "AnalysisSummary must stay in explicit boundary/projection modules"
                )
    return violations


def _check_report_pdf_entrypoint_uses_prepared_input() -> list[str]:
    path = VIBESENSOR_DIR / "app" / "container.py"
    tree = _parse_python(path)
    if tree is None:
        return []
    violations: list[str] = []
    found_entrypoint = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_pdf_bytes":
            found_entrypoint = True
            if not node.args.args:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "_build_pdf_bytes must accept PreparedReportInput"
                )
                continue
            annotation = node.args.args[0].annotation
            if not (
                isinstance(annotation, ast.Name)
                and annotation.id == "PreparedReportInput"
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "_build_pdf_bytes must accept PreparedReportInput"
                )
        if isinstance(node, ast.ImportFrom) and (
            node.module == "vibesensor.shared.boundaries.analysis_payload"
        ):
            if any(alias.name == "AnalysisSummary" for alias in node.names):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "container PDF entrypoint must not import AnalysisSummary"
                )
        if isinstance(node, ast.Name) and node.id == "prepare_history_report_analysis":
            violations.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                "container PDF entrypoint must not call prepare_history_report_analysis"
            )
    if not found_entrypoint:
        violations.append(
            f"{path.relative_to(REPO_ROOT)}: missing _build_pdf_bytes entrypoint"
        )
    return violations


_FORBIDDEN_DOMAIN_IMPORTS = (
    "vibesensor.adapters",
    "vibesensor.infra",
    "vibesensor.shared.types",
    "vibesensor.use_cases",
)


def _collect_domain_import_violations() -> list[str]:
    violations: list[str] = []
    domain_dir = VIBESENSOR_DIR / "domain"
    for path in _python_files(domain_dir):
        for lineno, module, names, _level in _scan_imports(path):
            if any(module.startswith(prefix) for prefix in _FORBIDDEN_DOMAIN_IMPORTS):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: from {module} import ..."
                )
            for name in names:
                if any(name.startswith(prefix) for prefix in _FORBIDDEN_DOMAIN_IMPORTS):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: import {name}"
                    )
    return violations


def _check_new_domain_modules_keep_import_isolation() -> list[str]:
    domain_modules = [
        VIBESENSOR_DIR / "domain" / "snapshots.py",
        VIBESENSOR_DIR / "domain" / "order_match.py",
        VIBESENSOR_DIR / "domain" / "driving_segment.py",
        VIBESENSOR_DIR / "domain" / "location_hotspot.py",
    ]
    violations: list[str] = []
    for path in domain_modules:
        if not path.exists():
            continue
        for entry in _imports_from_analysis(path):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {entry}")
        for entry in _imports_from_prefixes(path, ("vibesensor.shared.boundaries",)):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {entry}")
    return violations


def _shared_type_module_files() -> list[Path]:
    return [
        path
        for path in _python_files(VIBESENSOR_DIR / "shared" / "types")
        if path.name != "__init__.py"
    ]


def _check_backend_types_module_removed() -> list[str]:
    path = VIBESENSOR_DIR / "shared" / "types" / "backend_types.py"
    if path.exists():
        return [
            f"{path.relative_to(REPO_ROOT)} must not be reintroduced; use focused shared type owners instead"
        ]
    return []


def _check_shared_types_do_not_import_from_infra() -> list[str]:
    violations: list[str] = []
    for path in _shared_type_module_files():
        for lineno, module, _names, _level in _scan_imports(path):
            if module.startswith("vibesensor.infra"):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: from {module} import ..."
                )
    return violations


def _check_shared_types_no_domain_factory_methods() -> list[str]:
    factory_methods: list[str] = []
    for path in _shared_type_module_files():
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in {
                "to_car",
                "to_sensor",
                "to_car_snapshot",
            }:
                factory_methods.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {node.name}()"
                )
    return factory_methods


_LAYERS = ("domain", "shared", "use_cases", "infra", "adapters", "app")
_ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "shared": frozenset({"domain"}),
    "use_cases": frozenset({"domain", "shared"}),
    "infra": frozenset({"domain", "shared"}),
    "adapters": frozenset({"domain", "shared", "infra", "use_cases"}),
    "app": frozenset({"domain", "shared", "use_cases", "infra", "adapters"}),
}


def _classify_layer(rel_path: str) -> str:
    first = rel_path.split("/")[0]
    if first in _LAYERS:
        return first
    if first == "cli":
        return "app"
    return "shared"


def _import_target_layer(module: str) -> str | None:
    if not module.startswith("vibesensor"):
        return None
    rest = module.removeprefix("vibesensor.")
    if not rest:
        return None
    top = rest.split(".")[0]
    if top in _LAYERS:
        return top
    if top == "cli":
        return "app"
    return "shared"


_KNOWN_VIOLATIONS: frozenset[tuple[str, str]] = frozenset()


def _scan_layer_boundary_violations() -> set[tuple[str, str]]:
    violations: set[tuple[str, str]] = set()
    for path in _python_files(VIBESENSOR_DIR):
        if "static" in path.parts:
            continue
        rel = str(path.relative_to(VIBESENSOR_DIR))
        layer = _classify_layer(rel)
        allowed = _ALLOWED_IMPORTS[layer]
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                target = _import_target_layer(module)
                if target is None or target == layer:
                    continue
                if target not in allowed:
                    violations.add((rel, module))
    return violations


def _check_layer_boundaries() -> list[str]:
    violations = _scan_layer_boundary_violations()
    failures: list[str] = []
    new_violations = violations - _KNOWN_VIOLATIONS
    if new_violations:
        failures.append(
            "New layer-boundary violations found:\n  "
            + "\n  ".join(f"{src} -> {mod}" for src, mod in sorted(new_violations))
        )
    stale = _KNOWN_VIOLATIONS - violations
    if stale:
        failures.append(
            "Stale layer-boundary allowlist entries found:\n  "
            + "\n  ".join(f"{src} -> {mod}" for src, mod in sorted(stale))
        )
    for layer in _LAYERS:
        expected = VIBESENSOR_DIR / ("app" if layer == "app" else layer)
        if not expected.is_dir():
            failures.append(
                f"Missing layer directory: {expected.relative_to(REPO_ROOT)}"
            )
    for layer, allowed in _ALLOWED_IMPORTS.items():
        for target in allowed:
            peer_allowed = _ALLOWED_IMPORTS.get(target, frozenset())
            if layer in peer_allowed:
                failures.append(f"Layer DAG cycle detected: {layer} <-> {target}")
    return failures


def _check_summary_builder_does_not_define_normalize_lang() -> list[str]:
    path = VIBESENSOR_DIR / "use_cases" / "diagnostics" / "summary_builder.py"
    tree = _parse_python(path)
    if tree is None:
        return []
    failures: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_lang":
            failures.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: summary_builder must not define normalize_lang()"
            )
    return failures


_INTERNAL_DIAGNOSTICS_MODULES = (
    "signal_aggregation.py",
    "run_data_preparation.py",
    "peaks/table.py",
    "spectrogram.py",
    "plots.py",
    "summary_builder.py",
)
_FORBIDDEN_ANALYSIS_PAYLOAD_NAMES = frozenset(
    {
        "AmpVsPhaseRow",
        "FindingPayload",
        "FreqVsSpeedByFindingSeries",
        "MatchedAmpVsSpeedSeries",
        "PeakTableRow",
        "PhaseBoundary",
        "PhaseSegmentOut",
        "PhaseSpeedBreakdownRow",
        "PlotDataResult",
        "SpectrogramResult",
        "SpeedBreakdownRow",
    }
)


def _check_diagnostics_boundary_types() -> list[str]:
    failures: list[str] = []
    diagnostics_dir = VIBESENSOR_DIR / "use_cases" / "diagnostics"
    for path_name in _INTERNAL_DIAGNOSTICS_MODULES:
        path = diagnostics_dir / path_name
        tree = _parse_python(path)
        if tree is None:
            continue
        bad_imports: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "vibesensor.shared.boundaries.analysis_payload":
                continue
            bad = sorted(
                alias.name
                for alias in node.names
                if alias.name in _FORBIDDEN_ANALYSIS_PAYLOAD_NAMES
            )
            if bad:
                bad_imports.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {', '.join(bad)}"
                )
        failures.extend(bad_imports)
    summary_builder = diagnostics_dir / "summary_builder.py"
    tree = _parse_python(summary_builder)
    if tree is not None:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "vibesensor.shared.boundaries.finding"
                and any(
                    alias.name == "finding_payload_from_domain" for alias in node.names
                )
            ):
                failures.append(
                    f"{summary_builder.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "summary_builder must leave finding projection in the boundary seam"
                )
    return failures


def _check_domain_package_has_no_payload_type_imports() -> list[str]:
    forbidden = {"FindingPayload", "AnalysisSummary"}
    violations: list[str] = []
    for path in _python_files(VIBESENSOR_DIR / "domain"):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for alias in node.names:
                if alias.name in forbidden:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports {alias.name}"
                    )
    return violations


def _check_domain_modules_do_not_import_analysis_coordinator() -> list[str]:
    violations: list[str] = []
    for path in _python_files(VIBESENSOR_DIR / "domain"):
        for lineno, module, names, _level in _scan_imports(path):
            if "analysis" in module and "AnalysisResult" in names:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: imports AnalysisResult from {module}"
                )
    return violations


def _check_boundary_and_report_modules_do_not_import_analysis_coordinator() -> list[
    str
]:
    paths = [
        VIBESENSOR_DIR / "shared" / "boundaries",
        VIBESENSOR_DIR / "adapters" / "pdf",
    ]
    violations: list[str] = []
    for root in paths:
        for path in _python_files(root):
            for lineno, module, names, _level in _scan_imports(path):
                if "analysis" in module and "AnalysisResult" in names:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: imports AnalysisResult from {module}"
                    )
    return violations


def _check_planning_service_has_no_payload_imports() -> list[str]:
    path = VIBESENSOR_DIR / "domain" / "test_plan.py"
    tree = _parse_python(path)
    if tree is None:
        return []
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        module = getattr(node, "module", "") or ""
        names = [alias.name for alias in node.names]
        all_refs = module + " " + " ".join(names)
        if "FindingPayload" in all_refs:
            violations.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports FindingPayload"
            )
        if "AnalysisSummary" in all_refs:
            violations.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports AnalysisSummary"
            )
    return violations


def _check_suspected_vibration_origin_is_boundary_only() -> list[str]:
    violations: list[str] = []
    for path in _python_files(VIBESENSOR_DIR / "domain"):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if any(alias.name == "SuspectedVibrationOrigin" for alias in node.names):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports SuspectedVibrationOrigin"
                )
    return violations


def _check_types_modules_do_not_duplicate_domain_concepts_as_typeddicts() -> list[str]:
    domain_exports = set(
        getattr(importlib.import_module("vibesensor.domain"), "__all__", ())
    )
    violations: list[str] = []
    for path in _python_files(VIBESENSOR_DIR):
        if not path.name.endswith("_types.py"):
            continue
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                isinstance(base, ast.Name) and base.id == "TypedDict"
                for base in node.bases
            ):
                continue
            if node.name in domain_exports:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: duplicates domain export {node.name}"
                )
    return violations


def _check_domain_vos_have_no_dict_accepting_factory_methods() -> list[str]:
    domain_dir = VIBESENSOR_DIR / "domain"
    domain_files = [
        path for path in domain_dir.glob("*.py") if path.name != "__init__.py"
    ]
    untyped_names = {"dict", "Dict", "MutableMapping"}
    allowlist = {
        ("ConfigurationSnapshot", "from_metadata"),
        ("TireSpec", "from_aspects"),
    }
    violations: list[str] = []
    seen_classes: set[int] = set()
    for path in domain_files:
        module_name = f"vibesensor.domain.{path.stem}"
        mod = importlib.import_module(module_name)
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if not isinstance(obj, type):
                continue
            if id(obj) in seen_classes:
                continue
            seen_classes.add(id(obj))
            for method_name in dir(obj):
                if (obj.__name__, method_name) in allowlist:
                    continue
                method = getattr(obj, method_name, None)
                if method is None:
                    continue
                static_attr = inspect.getattr_static(obj, method_name, None)
                if not (
                    isinstance(static_attr, classmethod)
                    or isinstance(static_attr, staticmethod)
                ):
                    continue
                try:
                    raw = method.__func__ if hasattr(method, "__func__") else method
                    hints = inspect.get_annotations(raw)
                except Exception:
                    continue
                for param_name, annotation in hints.items():
                    if param_name == "return":
                        continue
                    ann_str = str(annotation)
                    if any(untyped in ann_str for untyped in untyped_names):
                        violations.append(
                            f"{obj.__name__}.{method_name}() param {param_name!r} has untyped annotation: "
                            f"{ann_str}"
                        )
    return violations


def _check_post_analysis_uses_suitability_check() -> list[str]:
    path = VIBESENSOR_DIR / "use_cases" / "run" / "post_analysis_summary.py"
    source = _read_text(path)
    if "SuitabilityCheck" not in source:
        return [
            f"{path.relative_to(REPO_ROOT)} must use SuitabilityCheck domain objects for suitability construction"
        ]
    return []


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


def _check_domain_import_direction() -> list[str]:
    forbidden_prefixes = (
        "vibesensor.shared.boundaries",
        "vibesensor.adapters",
        "vibesensor.infra",
    )
    violations: list[str] = []
    for path in (VIBESENSOR_DIR / "domain").glob("*.py"):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if any(node.module.startswith(prefix) for prefix in forbidden_prefixes):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: imports from {node.module}"
                    )
    return violations


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
        "vibration_origin.py": {"_source_from_payload"},
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


Check = tuple[str, Callable[[], list[str]]]
CHECKS: tuple[Check, ...] = (
    (
        "Backend tests avoid source introspection APIs",
        _check_backend_tests_do_not_use_source_introspection,
    ),
    (
        "PDF/report modules stay analysis-free at module level",
        _check_report_modules_do_not_import_analysis,
    ),
    (
        "PDF/report modules use shared strength math",
        _check_report_modules_use_shared_strength_math,
    ),
    (
        "Diagnostics analysis modules stay i18n-free",
        _check_analysis_modules_do_not_import_i18n,
    ),
    (
        "UI code avoids local strength-metric math",
        _check_ui_code_does_not_compute_strength_metrics,
    ),
    (
        "Strength metric math stays centralized",
        _check_strength_metric_definition_is_centralized,
    ),
    (
        "No local diagnostics vibration_strength module exists",
        _check_server_has_no_local_vibration_strength_module,
    ),
    (
        "External modules use the diagnostics public API",
        _check_external_modules_use_analysis_public_api,
    ),
    (
        "Live processing stays analysis-free",
        _check_live_processing_does_not_import_analysis,
    ),
    (
        "Recorder live-start snapshot stays under lock",
        _check_metrics_log_reads_live_start_under_lock,
    ),
    (
        "History services avoid HTTPException",
        _check_history_services_do_not_import_httpexception,
    ),
    (
        "History report loader avoids AnalysisSummary dict re-wraps",
        _check_history_report_loader_avoids_analysis_dict_rewrap,
    ),
    (
        "AnalysisSummary stays at boundaries",
        _check_analysis_summary_stays_at_boundaries,
    ),
    (
        "Report PDF entrypoint uses prepared input",
        _check_report_pdf_entrypoint_uses_prepared_input,
    ),
    ("Domain modules avoid outer-layer imports", _collect_domain_import_violations),
    (
        "New domain modules keep import isolation",
        _check_new_domain_modules_keep_import_isolation,
    ),
    (
        "backend_types catch-all module stays removed",
        _check_backend_types_module_removed,
    ),
    (
        "Shared backend types avoid infra imports",
        _check_shared_types_do_not_import_from_infra,
    ),
    (
        "Shared types avoid domain factory methods",
        _check_shared_types_no_domain_factory_methods,
    ),
    ("Layer boundaries stay acyclic and clean", _check_layer_boundaries),
    (
        "summary_builder keeps normalize_lang in report_i18n",
        _check_summary_builder_does_not_define_normalize_lang,
    ),
    (
        "Diagnostics internals avoid boundary payload TypedDicts",
        _check_diagnostics_boundary_types,
    ),
    (
        "Domain package avoids payload type imports",
        _check_domain_package_has_no_payload_type_imports,
    ),
    (
        "Domain modules avoid AnalysisResult",
        _check_domain_modules_do_not_import_analysis_coordinator,
    ),
    (
        "Boundary/report modules avoid AnalysisResult",
        _check_boundary_and_report_modules_do_not_import_analysis_coordinator,
    ),
    (
        "Domain planning service avoids payload imports",
        _check_planning_service_has_no_payload_imports,
    ),
    (
        "SuspectedVibrationOrigin stays boundary-only",
        _check_suspected_vibration_origin_is_boundary_only,
    ),
    (
        "*_types modules avoid duplicating domain concepts as TypedDicts",
        _check_types_modules_do_not_duplicate_domain_concepts_as_typeddicts,
    ),
    (
        "Domain factory methods avoid raw dict/Mapping annotations",
        _check_domain_vos_have_no_dict_accepting_factory_methods,
    ),
    (
        "post_analysis_summary uses SuitabilityCheck domain objects",
        _check_post_analysis_uses_suitability_check,
    ),
    (
        "domain/ avoids outer package imports",
        _check_domain_does_not_import_outer_packages,
    ),
    (
        "shared/boundaries avoids outer-layer imports",
        _check_boundaries_do_not_import_outer_layers,
    ),
    (
        "shared/boundaries avoids analysis imports",
        _check_boundaries_do_not_import_analysis,
    ),
    ("Signature stays out of adapter layers", _check_signature_confinement),
    ("Domain import direction stays inward", _check_domain_import_direction),
    (
        "Domain code avoids raw tire field access",
        _check_domain_code_does_not_access_raw_tire_fields,
    ),
    (
        "domain/use_cases avoid CarConfig",
        _check_domain_and_use_cases_do_not_import_car_config,
    ),
    (
        "domain/use_cases avoid raw aspects dict access",
        _check_domain_and_use_cases_do_not_read_raw_aspects_dict_keys,
    ),
    (
        "Boundary layers avoid constructing FindingKind",
        _check_boundary_owns_no_meaning_finding_kind,
    ),
    (
        "Boundary layers avoid business VibrationSource construction",
        _check_boundary_owns_no_meaning_vibration_source,
    ),
    ("RunStatus imports stay in the domain layer", _check_run_status_from_domain_only),
    (
        "Run lifecycle class stays out of analysis/report code",
        _check_run_lifecycle_only,
    ),
)


def main() -> int:
    failures = 0
    for title, check in CHECKS:
        issues = check()
        if issues:
            print(f"FAIL: {title}")
            for issue in issues:
                for line in str(issue).splitlines():
                    print(f"  {line}")
            failures += len(issues)
        else:
            print(f"OK: {title}")
    if failures:
        print(f"Static guard failures: {failures}")
        return 1
    print("All backend static guards passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
