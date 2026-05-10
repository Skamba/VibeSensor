# ruff: noqa: F403,F405
"""Type-module organization and package structure guards."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

from .core_utils import *


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


_CHECK_BACKEND_TYPES_MODULE_REMOVED = _path_absence_check(
    VIBESENSOR_DIR / "shared" / "types" / "backend_types.py",
    "apps/server/vibesensor/shared/types/backend_types.py must not be reintroduced; use focused shared type owners instead",
)

_CHECK_SHARED_TYPES_DO_NOT_IMPORT_FROM_INFRA = _import_prefix_check(
    paths_provider=_shared_type_module_files,
    prefixes=("vibesensor.infra",),
    failure_template="{path} must not import infra collaborators directly:\n{violations}",
)


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


def _check_isolated_server_runtime_owner() -> list[str]:
    failures: list[str] = []
    old_file = VIBESENSOR_DIR / "shared" / "subprocess_server.py"
    new_file = VIBESENSOR_DIR / "use_cases" / "isolated_server_runtime.py"
    if old_file.exists():
        failures.append(
            f"{old_file.relative_to(REPO_ROOT)} should not exist; isolated server subprocess orchestration belongs in use_cases/isolated_server_runtime.py"
        )
    if not new_file.exists():
        failures.append(
            f"Missing isolated server runtime owner: {new_file.relative_to(REPO_ROOT)}"
        )
    scan_dirs = [VIBESENSOR_DIR, REPO_ROOT / "tools" / "tests"]
    for scan_dir in scan_dirs:
        for path in _python_files(scan_dir):
            source = _read_text(path)
            if "from vibesensor.shared.subprocess_server import" in source or (
                "import vibesensor.shared.subprocess_server" in source
            ):
                failures.append(
                    f"{path.relative_to(REPO_ROOT)} imports removed shared/subprocess_server.py; use vibesensor.use_cases.isolated_server_runtime instead"
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
