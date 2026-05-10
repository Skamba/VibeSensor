# ruff: noqa: F403,F405
"""Analysis, report, live-processing, and dataflow guards."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .core_utils import *


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


def _check_fft_analysis_is_centralized() -> list[str]:
    canonical = VIBESENSOR_DIR / "shared" / "fft_analysis.py"
    legacy_wrapper = VIBESENSOR_DIR / "infra" / "processing" / "fft.py"
    failures: list[str] = []
    if legacy_wrapper.exists():
        failures.append(
            "apps/server/vibesensor/infra/processing/fft.py must stay removed; use vibesensor.shared.fft_analysis directly"
        )
    patterns = {
        "np.fft": "numpy.fft",
        "np.hanning(": "np.hanning",
        "scipy.fft": "scipy.fft",
        "scipy_fft.": "scipy_fft",
        "signal_windows.hann(": "signal_windows.hann",
        "pyfftw.": "pyfftw",
    }
    for path in _python_files(VIBESENSOR_DIR):
        if path == canonical:
            continue
        for lineno, line in enumerate(_read_text(path).splitlines(), start=1):
            for needle, label in patterns.items():
                if needle in line:
                    failures.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: FFT implementation details must stay in shared/fft_analysis.py; import shared helpers instead of {label}"
                    )
    return failures


_CHECK_SERVER_HAS_NO_LOCAL_VIBRATION_STRENGTH_MODULE = _path_absence_check(
    VIBESENSOR_DIR / "use_cases" / "diagnostics" / "vibration_strength.py",
    "apps/server/vibesensor/use_cases/diagnostics/vibration_strength.py should not exist; use vibesensor/vibration_strength.py",
)

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


def _check_canonical_dataflow_doc() -> list[str]:
    path = REPO_ROOT / "docs" / "dataflows.md"
    if not path.exists():
        return [
            f"{path.relative_to(REPO_ROOT)} must exist as the canonical four-flow map"
        ]
    source = _read_text(path)
    required_markers = (
        "# Canonical Dataflows",
        "## Live dataflow",
        "## Recording dataflow",
        "## Raw capture dataflow",
        "## Report dataflow",
        "docs/intake_buffering.md",
        "docs/run_lifecycle.md",
        "docs/analysis_pipeline.md",
        "docs/report_pipeline.md",
        "degraded",
        "missing",
        "replayable",
    )
    failures: list[str] = []
    for marker in required_markers:
        if marker not in source:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} must document the canonical flow map marker: {marker}"
            )
    return failures


def _check_recording_flow_uses_flush_and_persistence_writer() -> list[str]:
    logger_path = VIBESENSOR_DIR / "use_cases" / "run" / "logger.py"
    sample_flush_path = VIBESENSOR_DIR / "use_cases" / "run" / "sample_flush.py"
    persistence_writer_path = (
        VIBESENSOR_DIR / "use_cases" / "run" / "persistence_writer.py"
    )
    finalize_stages_path = VIBESENSOR_DIR / "use_cases" / "run" / "finalize_stages.py"
    logger_source = _read_text(logger_path)
    sample_flush_source = _read_text(sample_flush_path)
    persistence_writer_source = _read_text(persistence_writer_path)
    finalize_stages_source = _read_text(finalize_stages_path)
    failures: list[str] = []
    required_logger_markers = (
        "from vibesensor.use_cases.run.finalize_stages import",
        "def _finalize_active_run_locked(self, *, reason: str) -> ActiveRunFinalizeResult:",
        "return finalize_active_run(",
    )
    for marker in required_logger_markers:
        if marker not in logger_source:
            failures.append(
                f"{logger_path.relative_to(REPO_ROOT)} must route recording finalization through the dedicated finalize helper ({marker})"
            )
    required_sample_flush_markers = (
        "from vibesensor.use_cases.run.persistence_writer import RunPersistenceWriter",
        "self._persistence.append_rows(",
    )
    for marker in required_sample_flush_markers:
        if marker not in sample_flush_source:
            failures.append(
                f"{sample_flush_path.relative_to(REPO_ROOT)} must keep sample flush as the recording-to-persistence boundary ({marker})"
            )
    if "from vibesensor.adapters.persistence.history_db" in sample_flush_source:
        failures.append(
            f"{sample_flush_path.relative_to(REPO_ROOT)} must stay adapter-free; persistence_writer owns the history DB boundary"
        )
    required_finalize_stage_markers = (
        "sample_flush.append_records(",
        "persistence.ready_for_analysis(run_id)",
        "persistence.finalize_run(",
    )
    for marker in required_finalize_stage_markers:
        if marker not in finalize_stages_source:
            failures.append(
                f"{finalize_stages_path.relative_to(REPO_ROOT)} must own the recorder finalize stages ({marker})"
            )
    required_writer_markers = (
        "def ensure_history_run(",
        "history_db.aappend_samples(run_id, rows)",
    )
    for marker in required_writer_markers:
        if marker not in persistence_writer_source:
            failures.append(
                f"{persistence_writer_path.relative_to(REPO_ROOT)} must own the history DB append path for recorded rows ({marker})"
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


_CHECK_USE_CASES_DO_NOT_IMPORT_ADAPTERS_DIRECTLY = _import_prefix_check(
    paths_provider=lambda: _python_files(VIBESENSOR_DIR / "use_cases"),
    prefixes=("vibesensor.adapters",),
    failure_template=(
        "{path} must stay on shared/infra ports or adapter-local seams instead of "
        "importing adapters directly:\n{violations}"
    ),
)

_CHECK_ANALYSIS_AND_HISTORY_CORE_DO_NOT_IMPORT_PDF_ADAPTER = _import_prefix_check(
    paths_provider=lambda: _paths_from_roots(
        VIBESENSOR_DIR / "use_cases" / "diagnostics",
        VIBESENSOR_DIR / "use_cases" / "history",
        VIBESENSOR_DIR / "shared" / "boundaries" / "reporting",
    ),
    prefixes=("vibesensor.adapters.pdf",),
    failure_template=(
        "{path} must not import the PDF adapter directly; keep report/analysis "
        "core on report-boundary seams such as PreparedReportInput or "
        "ReportDocument:\n{violations}"
    ),
)


def _live_telemetry_surface_files() -> list[Path]:
    files = _live_processing_files()
    for path in (
        VIBESENSOR_DIR / "infra" / "runtime" / "ws_payload_projection.py",
        VIBESENSOR_DIR / "infra" / "runtime" / "ws_broadcast.py",
        VIBESENSOR_DIR / "infra" / "runtime" / "processing_tick.py",
    ):
        if path.exists():
            files.append(path)
    return sorted(dict.fromkeys(files))


_CHECK_LIVE_SURFACES_DO_NOT_IMPORT_POST_RUN_CONCLUSIONS = _import_prefix_check(
    paths_provider=_live_telemetry_surface_files,
    prefixes=(
        "vibesensor.use_cases.diagnostics",
        "vibesensor.use_cases.history",
        "vibesensor.shared.boundaries.reporting",
        "vibesensor.adapters.pdf",
    ),
    failure_template=(
        "{path} must keep live telemetry on runtime/transport seams instead of "
        "importing post-run diagnosis/report conclusion modules:\n{violations}"
    ),
)
