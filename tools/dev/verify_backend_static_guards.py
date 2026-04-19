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
        live_start_idx = source.index("recorder._live_start_mono_s")
        build_idx = source.index("build_sample_records")
    except ValueError as exc:
        return [
            f"{path.relative_to(REPO_ROOT)} missing expected recorder lock-order markers: {exc}"
        ]
    if not (lock_idx < live_start_idx < build_idx):
        return [
            f"{path.relative_to(REPO_ROOT)} must read _live_start_mono_s inside the "
            "recorder-lock-protected flush path before build_sample_records"
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
        "shared/boundaries/reporting/preparation.py",
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
            if node.module not in (
                "vibesensor.shared.types.history_analysis_contracts",
            ):
                continue
            if any(alias.name == "AnalysisSummary" for alias in node.names):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "AnalysisSummary must stay in explicit boundary/projection modules"
                )
    return violations


_DIAGNOSTICS_FACADE_NAMES = frozenset(
    {
        "AnalysisResult",
        "AnalysisSampleInput",
        "FindingsBuilder",
        "RunAnalysis",
        "build_findings_for_samples",
        "build_order_bands",
        "load_run",
        "vehicle_orders_hz",
    }
)


def _check_modules_avoid_diagnostics_facade_reexports() -> list[str]:
    diagnostics_init_path = VIBESENSOR_DIR / "use_cases" / "diagnostics" / "__init__.py"
    failures: list[str] = []
    for path in _python_files(VIBESENSOR_DIR):
        if path == diagnostics_init_path:
            continue
        for lineno, module, names, _level in _scan_imports(path):
            if module != "vibesensor.use_cases.diagnostics":
                continue
            facade_names = sorted(
                name for name in names if name in _DIAGNOSTICS_FACADE_NAMES
            )
            if facade_names:
                failures.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: import canonical diagnostics modules directly instead of "
                    f"the diagnostics package facade ({', '.join(facade_names)})"
                )
    return failures


def _check_summary_payload_uses_build_context() -> list[str]:
    path = (
        VIBESENSOR_DIR
        / "shared"
        / "boundaries"
        / "summary_serialization"
        / "_summary.py"
    )
    tree = _parse_python(path)
    if tree is None:
        return [f"Unable to parse {path.relative_to(REPO_ROOT)}"]
    build_context_found = False
    build_summary_signature_ok = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "AnalysisSummaryBuildContext"
        ):
            build_context_found = True
        if isinstance(node, ast.FunctionDef) and node.name == "build_summary_payload":
            build_summary_signature_ok = (
                len(node.args.args) == 1
                and not node.args.kwonlyargs
                and node.args.args[0].arg == "context"
            )
    failures: list[str] = []
    if not build_context_found:
        failures.append(
            f"{path.relative_to(REPO_ROOT)} must define AnalysisSummaryBuildContext"
        )
    if not build_summary_signature_ok:
        failures.append(
            f"{path.relative_to(REPO_ROOT)} must accept a single context object in build_summary_payload"
        )
    return failures


def _check_settings_services_use_shared_update_helper() -> list[str]:
    settings_path = VIBESENSOR_DIR / "infra" / "config" / "settings_persistence.py"
    car_settings_path = VIBESENSOR_DIR / "infra" / "config" / "car_settings.py"
    sensor_settings_path = VIBESENSOR_DIR / "infra" / "config" / "sensor_settings.py"
    speed_source_settings_path = (
        VIBESENSOR_DIR / "infra" / "config" / "speed_source_settings.py"
    )
    transaction_path = VIBESENSOR_DIR / "infra" / "config" / "settings_transaction.py"
    ui_preferences_path = VIBESENSOR_DIR / "infra" / "config" / "ui_preferences.py"
    settings_source = _read_text(settings_path)
    car_settings_source = _read_text(car_settings_path)
    sensor_settings_source = _read_text(sensor_settings_path)
    speed_source_settings_source = _read_text(speed_source_settings_path)
    transaction_source = _read_text(transaction_path)
    ui_preferences_source = _read_text(ui_preferences_path)
    failures: list[str] = []
    if (
        "from vibesensor.infra.config.settings_transaction import update_with_rollback"
        not in settings_source
    ):
        failures.append(
            f"{settings_path.relative_to(REPO_ROOT)} must import update_with_rollback from settings_transaction"
        )
    if "except PersistenceError" in settings_source:
        failures.append(
            f"{settings_path.relative_to(REPO_ROOT)} must not handle PersistenceError directly; delegate to settings_transaction"
        )
    if transaction_source.count("except PersistenceError") != 1:
        failures.append(
            f"{transaction_path.relative_to(REPO_ROOT)} must keep PersistenceError rollback handling in one helper"
        )
    if "except PersistenceError" in car_settings_source:
        failures.append(
            f"{car_settings_path.relative_to(REPO_ROOT)} must delegate rollback handling to settings_transaction"
        )
    if "except PersistenceError" in sensor_settings_source:
        failures.append(
            f"{sensor_settings_path.relative_to(REPO_ROOT)} must delegate rollback handling to settings_transaction"
        )
    if "except PersistenceError" in speed_source_settings_source:
        failures.append(
            f"{speed_source_settings_path.relative_to(REPO_ROOT)} must delegate rollback handling to settings_transaction"
        )
    if "except PersistenceError" in ui_preferences_source:
        failures.append(
            f"{ui_preferences_path.relative_to(REPO_ROOT)} must delegate rollback handling to settings_transaction"
        )
    return failures


def _check_health_snapshot_moves_out_of_http_adapter() -> list[str]:
    health_builder_path = VIBESENSOR_DIR / "adapters" / "http" / "health_snapshot.py"
    health_route_path = VIBESENSOR_DIR / "adapters" / "http" / "health.py"
    failures: list[str] = []
    if health_builder_path.exists():
        failures.append(
            f"{health_builder_path.relative_to(REPO_ROOT)} should not exist; health assembly belongs in infra/runtime"
        )
    route_source = _read_text(health_route_path)
    if (
        "from vibesensor.infra.runtime.health_snapshot import build_system_health_snapshot"
        not in route_source
    ):
        failures.append(
            f"{health_route_path.relative_to(REPO_ROOT)} must import build_system_health_snapshot from vibesensor.infra.runtime.health_snapshot"
        )
    return failures


def _check_clients_http_adapter_uses_protocol_dependencies() -> list[str]:
    clients_path = VIBESENSOR_DIR / "adapters" / "http" / "clients.py"
    dependencies_path = VIBESENSOR_DIR / "adapters" / "http" / "dependencies.py"
    clients_source = _read_text(clients_path)
    dependencies_source = _read_text(dependencies_path)
    failures: list[str] = []
    forbidden_markers = (
        "from vibesensor.infra.runtime.client_snapshot import",
        "from vibesensor.infra.processing",
        "from vibesensor.infra.runtime.registry",
    )
    for marker in forbidden_markers:
        if marker in clients_source:
            failures.append(
                f"{clients_path.relative_to(REPO_ROOT)} must not import concrete infra client/runtime helpers ({marker})"
            )
    required_clients_markers = (
        "ClientRegistryProtocol",
        "ClientProcessorProtocol",
        "ClientControlPlaneProtocol",
        "from vibesensor.shared.boundaries.clients import snapshot_for_api",
    )
    for marker in required_clients_markers:
        if marker not in clients_source:
            failures.append(
                f"{clients_path.relative_to(REPO_ROOT)} must depend on protocol-based client adapter collaborators ({marker})"
            )
    required_dependencies_markers = (
        "class ClientRegistryProtocol(ClientSnapshotSource, Protocol):",
        "class ClientProcessorProtocol(Protocol):",
        "class ClientControlPlaneProtocol(Protocol):",
    )
    for marker in required_dependencies_markers:
        if marker not in dependencies_source:
            failures.append(
                f"{dependencies_path.relative_to(REPO_ROOT)} must define focused client adapter protocols ({marker})"
            )
    return failures


def _check_route_facing_http_modules_avoid_infra_imports() -> list[str]:
    http_dir = VIBESENSOR_DIR / "adapters" / "http"
    target_paths = [
        http_dir / "clients.py",
        http_dir / "router.py",
        http_dir / "route_bundles.py",
        *sorted((http_dir / "settings").glob("*.py")),
    ]
    failures: list[str] = []
    for path in target_paths:
        for lineno, module, _names, level in _scan_imports(path):
            if level or not module or not module.startswith("vibesensor.infra"):
                continue
            failures.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: route-facing HTTP modules must depend on adapter/shared ports instead of importing infra collaborators directly ({module})"
            )
    return failures


def _check_http_route_modules_stay_split_and_focused() -> list[str]:
    http_dir = VIBESENSOR_DIR / "adapters" / "http"
    settings_legacy_path = http_dir / "settings.py"
    settings_init_path = http_dir / "settings" / "__init__.py"
    route_bundles_path = http_dir / "route_bundles.py"
    router_path = http_dir / "router.py"
    clients_path = http_dir / "clients.py"
    failures: list[str] = []
    if settings_legacy_path.exists():
        failures.append(
            f"{settings_legacy_path.relative_to(REPO_ROOT)} should not exist; settings routes belong under adapters/http/settings/"
        )
    line_limits = {
        settings_init_path: 120,
        route_bundles_path: 140,
        router_path: 60,
        clients_path: 220,
    }
    for path, limit in line_limits.items():
        line_count = len(_read_text(path).splitlines())
        if line_count > limit:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} should stay focused after the route split (currently {line_count} lines; limit {limit})"
            )
    for path, description in (
        (settings_init_path, "settings micro-router composition"),
        (route_bundles_path, "route-bundle composition"),
        (router_path, "top-level router composition"),
    ):
        if "@router." in _read_text(path):
            failures.append(
                f"{path.relative_to(REPO_ROOT)} should stay {description} only; endpoint decorators belong in leaf route modules"
            )
    if "/api/settings/" in _read_text(clients_path):
        failures.append(
            f"{clients_path.relative_to(REPO_ROOT)} must stay client-focused instead of reabsorbing settings endpoints"
        )
    return failures


def _check_sensor_metadata_writes_stay_in_settings_boundary() -> list[str]:
    ports_path = VIBESENSOR_DIR / "shared" / "ports.py"
    http_dir = VIBESENSOR_DIR / "adapters" / "http"
    clients_path = http_dir / "clients.py"
    ports_source = _read_text(ports_path)
    failures: list[str] = []
    for marker in (
        "class SensorMetadataStore(SensorMetadataReader, Protocol):",
        "def assign_sensor_location(self, sensor_id: str, location_code: str) -> SensorsByMacPayload: ...",
    ):
        if marker not in ports_source:
            failures.append(
                f"{ports_path.relative_to(REPO_ROOT)} must keep the canonical SensorMetadataStore write surface ({marker})"
            )
    if not _attribute_access_lines(clients_path, "assign_sensor_location"):
        failures.append(
            f"{clients_path.relative_to(REPO_ROOT)} must delegate client location writes through assign_sensor_location()"
        )
    for attr_name in ("set_sensor", "remove_sensor"):
        attr_lines = _attribute_access_lines(clients_path, attr_name)
        if attr_lines:
            failures.append(
                f"{clients_path.relative_to(REPO_ROOT)} must not call {attr_name} directly; client routes should delegate through assign_sensor_location() (lines {attr_lines})"
            )
    for path in _python_files(http_dir):
        for attr_name in ("set_sensor", "remove_sensor"):
            attr_lines = _attribute_access_lines(path, attr_name)
            if attr_lines:
                failures.append(
                    f"{path.relative_to(REPO_ROOT)} must not expose raw sensor metadata CRUD over HTTP; sensor metadata writes are limited to clients.py delegating assign_sensor_location() ({attr_name} at lines {attr_lines})"
                )
    for path in _python_files(http_dir):
        if path == clients_path:
            continue
        attr_lines = _attribute_access_lines(path, "assign_sensor_location")
        if attr_lines:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} must not delegate sensor location writes directly; keep assign_sensor_location() usage in clients.py only (lines {attr_lines})"
            )
    return failures


def _check_ws_broadcast_uses_projection_module() -> list[str]:
    ws_broadcast_path = VIBESENSOR_DIR / "infra" / "runtime" / "ws_broadcast.py"
    ws_projection_path = (
        VIBESENSOR_DIR / "infra" / "runtime" / "ws_payload_projection.py"
    )
    container_path = VIBESENSOR_DIR / "app" / "container.py"
    source = _read_text(ws_broadcast_path)
    container_source = _read_text(container_path)
    failures: list[str] = []
    if not ws_projection_path.exists():
        failures.append(
            f"{ws_projection_path.relative_to(REPO_ROOT)} must exist so live WS payload shaping has a dedicated projection module"
        )
        return failures
    if "class LiveWsPayloadSource(Protocol):" not in source:
        failures.append(
            f"{ws_broadcast_path.relative_to(REPO_ROOT)} must define a focused LiveWsPayloadSource port for shared payload assembly"
        )
    if (
        "from vibesensor.infra.runtime.ws_payload_projection import LiveWsPayloadProjector"
        in source
    ):
        failures.append(
            f"{ws_broadcast_path.relative_to(REPO_ROOT)} should not depend directly on the concrete LiveWsPayloadProjector once the broadcaster port seam exists"
        )
    forbidden_markers = (
        "from vibesensor.shared.boundaries.clients import snapshot_for_api",
        "from vibesensor.infra.runtime.rotational_speeds import",
        "resolve_speed()",
        "analysis_settings_snapshot()",
        "speed_source_config()",
        "clients_with_recent_data(",
        "multi_spectrum_payload(",
    )
    for marker in forbidden_markers:
        if marker in source:
            failures.append(
                f"{ws_broadcast_path.relative_to(REPO_ROOT)} should not shape live payloads directly once ws_payload_projection owns that logic ({marker})"
            )
    if "payload_source: LiveWsPayloadSource" not in source:
        failures.append(
            f"{ws_broadcast_path.relative_to(REPO_ROOT)} must accept a LiveWsPayloadSource collaborator"
        )
    if (
        "LiveWsPayloadProjector(" not in container_source
        or "payload_source=ws_payload_projector" not in container_source
    ):
        failures.append(
            f"{container_path.relative_to(REPO_ROOT)} must keep the concrete LiveWsPayloadProjector wired behind the broadcaster's payload_source port"
        )
    return failures


def _check_runtime_settings_use_explicit_reader_ports() -> list[str]:
    ports_path = VIBESENSOR_DIR / "shared" / "ports.py"
    container_path = VIBESENSOR_DIR / "app" / "container.py"
    runtime_state_path = VIBESENSOR_DIR / "app" / "runtime_state.py"
    logger_path = VIBESENSOR_DIR / "use_cases" / "run" / "logger.py"
    recorder_runtime_path = (
        VIBESENSOR_DIR / "use_cases" / "run" / "_recorder_runtime.py"
    )
    recorder_types_path = VIBESENSOR_DIR / "use_cases" / "run" / "_recorder_types.py"
    metadata_path = VIBESENSOR_DIR / "use_cases" / "run" / "run_metadata_builder.py"
    ports_source = _read_text(ports_path)
    container_source = _read_text(container_path)
    runtime_state_source = _read_text(runtime_state_path)
    logger_source = _read_text(logger_path)
    recorder_runtime_source = _read_text(recorder_runtime_path)
    recorder_types_source = _read_text(recorder_types_path)
    metadata_source = _read_text(metadata_path)
    failures: list[str] = []
    if (
        "class LanguageReader(Protocol):" not in ports_source
        or "def language(self) -> LanguageCode: ..." not in ports_source
    ):
        failures.append(
            f"{ports_path.relative_to(REPO_ROOT)} must define a focused LanguageReader protocol for runtime-facing language access"
        )
    if (
        "language_provider" in container_source
        or "_language_provider" in container_source
    ):
        failures.append(
            f"{container_path.relative_to(REPO_ROOT)} must not use ad hoc language-provider lambdas once runtime reader ports exist"
        )
    for marker in (
        "language_reader: LanguageReader",
        "language_reader=self.ui_preferences",
        "language_reader=runtime_settings.language_reader",
    ):
        if marker not in container_source:
            failures.append(
                f"{container_path.relative_to(REPO_ROOT)} must wire explicit runtime language-reader ports ({marker})"
            )
    if (
        "settings_store: SettingsReader" in runtime_state_source
        or "settings_reader: SettingsReader" not in runtime_state_source
    ):
        failures.append(
            f"{runtime_state_path.relative_to(REPO_ROOT)} must expose RuntimeState.settings_reader instead of the old settings_store alias"
        )
    for marker in (
        "settings_reader: SettingsReader | None = None",
        "language_reader: LanguageReader | None = None",
        "self._settings_reader = settings_reader",
        "self._language_reader = language_reader",
    ):
        if marker not in logger_source:
            failures.append(
                f"{logger_path.relative_to(REPO_ROOT)} must keep the recorder wired to explicit reader collaborators ({marker})"
            )
    if "_settings_store" in logger_source or "_language_provider" in logger_source:
        failures.append(
            f"{logger_path.relative_to(REPO_ROOT)} must not keep the old runtime settings/language aliases once explicit readers are in place"
        )
    if (
        "settings_store: SettingsReader | None" in recorder_runtime_source
        or "settings_reader: SettingsReader | None" not in recorder_runtime_source
    ):
        failures.append(
            f"{recorder_runtime_path.relative_to(REPO_ROOT)} must refer to the recorder's focused settings_reader seam"
        )
    if "language_reader=recorder._language_reader" not in recorder_types_source:
        failures.append(
            f"{recorder_types_path.relative_to(REPO_ROOT)} must forward the recorder's explicit language_reader into run metadata building"
        )
    if (
        "language_reader: LanguageReader | None = None" not in metadata_source
        or 'metadata.language = str(language_reader.language).strip().lower() or "en"'
        not in metadata_source
    ):
        failures.append(
            f"{metadata_path.relative_to(REPO_ROOT)} must build run metadata from the explicit LanguageReader port"
        )
    return failures


def _check_report_pdf_entrypoint_renders_report_document() -> list[str]:
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
                    "_build_pdf_bytes must accept ReportDocument"
                )
                continue
            annotation = node.args.args[0].annotation
            if not (
                isinstance(annotation, ast.Name) and annotation.id == "ReportDocument"
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "_build_pdf_bytes must accept ReportDocument"
                )
        if isinstance(node, ast.ImportFrom) and (
            node.module == "vibesensor.shared.types.history_analysis_contracts"
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


_ALLOWED_ROOT_MODULE_FILES = frozenset(
    {
        "__init__.py",
        "__main__.py",
        "_version.py",
        "report_i18n.py",
        "strength_bands.py",
        "vibration_strength.py",
    }
)


def _check_root_module_allowlist() -> list[str]:
    root_files = {
        path.name
        for path in VIBESENSOR_DIR.iterdir()
        if path.is_file() and path.suffix == ".py"
    }
    unexpected = sorted(root_files - _ALLOWED_ROOT_MODULE_FILES)
    if not unexpected:
        return []
    return [
        "Unexpected Python modules at apps/server/vibesensor/ root:\n  "
        + "\n  ".join(unexpected)
    ]


def _check_http_api_models_live_under_http_adapters() -> list[str]:
    failures: list[str] = []
    old_dir = VIBESENSOR_DIR / "shared" / "types" / "api_models"
    if old_dir.exists():
        failures.append(
            f"{old_dir.relative_to(REPO_ROOT)} should not exist; HTTP models belong under adapters/http/models/"
        )
    new_dir = VIBESENSOR_DIR / "adapters" / "http" / "models"
    if not new_dir.is_dir():
        failures.append(f"Missing HTTP model package: {new_dir.relative_to(REPO_ROOT)}")
    for path in _python_files(VIBESENSOR_DIR):
        source = _read_text(path)
        if "vibesensor.shared.types.api_models" in source:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} imports HTTP models from shared/types/api_models"
            )
    return failures


def _check_run_analysis_does_not_define_normalize_lang() -> list[str]:
    path = VIBESENSOR_DIR / "use_cases" / "diagnostics" / "run_analysis.py"
    tree = _parse_python(path)
    if tree is None:
        return []
    failures: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_lang":
            failures.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: run_analysis must not define normalize_lang()"
            )
    return failures


_INTERNAL_DIAGNOSTICS_MODULES = (
    "signal_aggregation.py",
    "run_data_preparation.py",
    "peaks/table.py",
    "spectrogram.py",
    "plots.py",
    "run_analysis.py",
    "analysis_pipeline.py",
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
            if node.module != "vibesensor.shared.types.analysis_views":
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
    for path in _python_files(diagnostics_dir):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "vibesensor.shared.boundaries.summary_fields.finding"
                and any(
                    alias.name == "finding_payload_from_domain" for alias in node.names
                )
            ):
                failures.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: "
                    "diagnostics core must leave finding projection in the boundary seam"
                )
    return failures


_DIAGNOSTICS_VIEW_TYPE_NAMES = frozenset(
    {
        "AmpVsPhaseRowData",
        "FreqVsSpeedByFindingSeriesData",
        "MatchedAmpVsSpeedSeriesData",
        "PeakClassificationRowView",
        "PeakTableRowData",
        "PhaseBoundaryData",
        "PhaseSegmentPlotData",
        "PhaseSpeedBreakdownRowData",
        "PlotDataResultData",
        "PlotSeriesBundle",
        "SpectrogramResultData",
        "SpeedBreakdownRowData",
    }
)


def _check_diagnostics_core_types_stay_core_only() -> list[str]:
    path = VIBESENSOR_DIR / "use_cases" / "diagnostics" / "_types.py"
    tree = _parse_python(path)
    if tree is None:
        return []
    return [
        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: move {node.name} to diagnostics/_view_types.py"
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name in _DIAGNOSTICS_VIEW_TYPE_NAMES
    ]


_UPDATES_ROOT_FORBIDDEN_MODULES = frozenset(
    {
        "esp_flash_manager.py",
        "esp_flash_runner.py",
        "esp_flash_types.py",
        "esp_serial.py",
        "firmware_bundle.py",
        "firmware_cache.py",
        "firmware_refresh.py",
        "firmware_release_fetcher.py",
        "firmware_types.py",
        "transport_coordinator.py",
        "transport_failures.py",
        "transport_lifecycles.py",
        "usb_transport.py",
        "wifi.py",
        "wifi_config.py",
        "wifi_diagnostics.py",
        "wifi_hotspot_recovery.py",
        "wifi_readiness.py",
        "wifi_uplink_setup.py",
        "release_fetcher.py",
        "release_validation.py",
        "releases.py",
    }
)


def _check_updates_package_subpackages() -> list[str]:
    updates_dir = VIBESENSOR_DIR / "use_cases" / "updates"
    failures: list[str] = []
    for module_name in sorted(_UPDATES_ROOT_FORBIDDEN_MODULES):
        if (updates_dir / module_name).exists():
            failures.append(
                f"{(updates_dir / module_name).relative_to(REPO_ROOT)} should live under a focused updates subpackage"
            )
    for package_name in ("firmware", "transport", "wifi", "releases"):
        init_path = updates_dir / package_name / "__init__.py"
        if not init_path.exists():
            failures.append(
                f"Missing updates subpackage initializer: {init_path.relative_to(REPO_ROOT)}"
            )
    return failures


def _check_shared_constants_package_split() -> list[str]:
    failures: list[str] = []
    old_file = VIBESENSOR_DIR / "shared" / "constants.py"
    if old_file.exists():
        failures.append(
            f"{old_file.relative_to(REPO_ROOT)} should not exist; split constants into shared/constants/"
        )
    constants_dir = VIBESENSOR_DIR / "shared" / "constants"
    required_files = (
        constants_dir / "__init__.py",
        constants_dir / "analysis.py",
        constants_dir / "dsp.py",
        constants_dir / "github.py",
        constants_dir / "phases.py",
        constants_dir / "type_checks.py",
        constants_dir / "ui.py",
        constants_dir / "units.py",
    )
    for path in required_files:
        if not path.exists():
            failures.append(
                f"Missing split constants module: {path.relative_to(REPO_ROOT)}"
            )
    for path in _python_files(VIBESENSOR_DIR):
        source = _read_text(path)
        if "from vibesensor.shared.constants import" in source:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} imports constants from the shared/constants root package"
            )
    return failures


def _check_run_context_split_owners() -> list[str]:
    failures: list[str] = []
    old_file = VIBESENSOR_DIR / "shared" / "run_context.py"
    if old_file.exists():
        failures.append(
            f"{old_file.relative_to(REPO_ROOT)} should not exist; split warning contracts from use_cases/run orchestration"
        )
    shared_warning = VIBESENSOR_DIR / "shared" / "run_context_warning.py"
    use_case_helper = VIBESENSOR_DIR / "use_cases" / "run" / "run_context.py"
    if not shared_warning.exists():
        failures.append(
            f"Missing shared warning contract module: {shared_warning.relative_to(REPO_ROOT)}"
        )
    if not use_case_helper.exists():
        failures.append(
            f"Missing run-context orchestration module: {use_case_helper.relative_to(REPO_ROOT)}"
        )
    for path in _python_files(VIBESENSOR_DIR):
        source = _read_text(path)
        if "from vibesensor.shared.run_context import" in source:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} imports removed shared/run_context.py"
            )
    return failures


def _check_settings_snapshot_boundary_location() -> list[str]:
    failures: list[str] = []
    legacy_files = (
        VIBESENSOR_DIR / "shared" / "boundaries" / "settings_snapshot.py",
        VIBESENSOR_DIR / "shared" / "boundaries" / "settings_snapshot_codec.py",
    )
    new_file = VIBESENSOR_DIR / "shared" / "boundaries" / "settings" / "snapshot.py"
    for legacy_file in legacy_files:
        if not legacy_file.exists():
            continue
        failures.append(
            f"{legacy_file.relative_to(REPO_ROOT)} should be removed in favor of "
            "shared/boundaries/settings/snapshot.py"
        )
    if not new_file.exists():
        failures.append(
            f"Missing settings snapshot boundary: {new_file.relative_to(REPO_ROOT)}"
        )
    for path in _python_files(VIBESENSOR_DIR):
        tree = _parse_python(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {
                "vibesensor.shared.boundaries.settings_snapshot",
                "vibesensor.shared.boundaries.settings_snapshot_codec",
            }:
                failures.append(
                    f"{path.relative_to(REPO_ROOT)} imports the old settings snapshot codec path"
                )
            if isinstance(node, ast.Import):
                if any(
                    alias.name
                    in {
                        "vibesensor.shared.boundaries.settings_snapshot",
                        "vibesensor.shared.boundaries.settings_snapshot_codec",
                    }
                    for alias in node.names
                ):
                    failures.append(
                        f"{path.relative_to(REPO_ROOT)} imports the old settings snapshot codec path"
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
        "Modules avoid diagnostics facade re-exports",
        _check_modules_avoid_diagnostics_facade_reexports,
    ),
    (
        "Summary serialization uses a build context",
        _check_summary_payload_uses_build_context,
    ),
    (
        "Root module allowlist stays tight",
        _check_root_module_allowlist,
    ),
    (
        "HTTP API models live under adapters/http",
        _check_http_api_models_live_under_http_adapters,
    ),
    (
        "SettingsStore uses one rollback helper",
        _check_settings_services_use_shared_update_helper,
    ),
    (
        "Health snapshot assembly stays out of HTTP adapters",
        _check_health_snapshot_moves_out_of_http_adapter,
    ),
    (
        "Clients HTTP adapter uses protocol deps",
        _check_clients_http_adapter_uses_protocol_dependencies,
    ),
    (
        "Route-facing HTTP modules avoid infra imports",
        _check_route_facing_http_modules_avoid_infra_imports,
    ),
    (
        "HTTP route modules stay split and focused",
        _check_http_route_modules_stay_split_and_focused,
    ),
    (
        "Sensor metadata writes stay in settings boundary",
        _check_sensor_metadata_writes_stay_in_settings_boundary,
    ),
    (
        "WsBroadcast uses projection module",
        _check_ws_broadcast_uses_projection_module,
    ),
    (
        "Runtime settings use explicit reader ports",
        _check_runtime_settings_use_explicit_reader_ports,
    ),
    (
        "Report PDF entrypoint renders report document",
        _check_report_pdf_entrypoint_renders_report_document,
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
    (
        "run_analysis keeps normalize_lang in report_i18n",
        _check_run_analysis_does_not_define_normalize_lang,
    ),
    (
        "Diagnostics internals avoid boundary payload TypedDicts",
        _check_diagnostics_boundary_types,
    ),
    (
        "Diagnostics core types stay sample-focused",
        _check_diagnostics_core_types_stay_core_only,
    ),
    (
        "Updates package keeps focused subpackages",
        _check_updates_package_subpackages,
    ),
    (
        "shared/constants stays split by concern",
        _check_shared_constants_package_split,
    ),
    (
        "Run-context helpers stay split between shared warnings and use_cases/run",
        _check_run_context_split_owners,
    ),
    (
        "Settings snapshot codec keeps a distinct filename",
        _check_settings_snapshot_boundary_location,
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
