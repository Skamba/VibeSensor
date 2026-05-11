# ruff: noqa: F403,F405
"""HTTP adapter, history, settings, websocket, and report adapter guards."""

from __future__ import annotations

import ast
from pathlib import Path

from .core_utils import *


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


def _route_facing_http_paths() -> list[Path]:
    http_dir = VIBESENSOR_DIR / "adapters" / "http"
    return [
        http_dir / "clients.py",
        http_dir / "router.py",
        http_dir / "route_bundles.py",
        *sorted((http_dir / "settings").glob("*.py")),
    ]


_CHECK_ROUTE_FACING_HTTP_MODULES_AVOID_INFRA_IMPORTS = _import_prefix_check(
    paths_provider=_route_facing_http_paths,
    prefixes=("vibesensor.infra",),
    failure_template=(
        "{path} must depend on adapter/shared ports instead of importing infra "
        "collaborators directly:\n{violations}"
    ),
)


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
    live_composition_path = VIBESENSOR_DIR / "app" / "composition" / "live.py"
    source = _read_text(ws_broadcast_path)
    live_composition_source = _read_text(live_composition_path)
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
        "LiveWsPayloadProjector(" not in live_composition_source
        or "payload_source=ws_payload_projector" not in live_composition_source
    ):
        failures.append(
            f"{live_composition_path.relative_to(REPO_ROOT)} must keep the concrete LiveWsPayloadProjector wired behind the broadcaster's payload_source port"
        )
    return failures


def _check_runtime_settings_use_explicit_reader_ports() -> list[str]:
    ports_path = VIBESENSOR_DIR / "shared" / "ports.py"
    live_composition_path = VIBESENSOR_DIR / "app" / "composition" / "live.py"
    settings_composition_path = VIBESENSOR_DIR / "app" / "composition" / "settings.py"
    runtime_state_path = VIBESENSOR_DIR / "app" / "runtime_state.py"
    logger_path = VIBESENSOR_DIR / "use_cases" / "run" / "logger.py"
    recorder_runtime_path = (
        VIBESENSOR_DIR / "use_cases" / "run" / "_recorder_runtime.py"
    )
    recorder_types_path = VIBESENSOR_DIR / "use_cases" / "run" / "_recorder_types.py"
    metadata_path = VIBESENSOR_DIR / "use_cases" / "run" / "run_metadata_builder.py"
    ports_source = _read_text(ports_path)
    live_composition_source = _read_text(live_composition_path)
    settings_composition_source = _read_text(settings_composition_path)
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
        "language_provider" in live_composition_source
        or "_language_provider" in live_composition_source
        or "language_provider" in settings_composition_source
        or "_language_provider" in settings_composition_source
    ):
        failures.append(
            "app composition must not use ad hoc language-provider lambdas once runtime reader ports exist"
        )
    required_markers = (
        (
            settings_composition_path,
            settings_composition_source,
            "language_reader: LanguageReader",
        ),
        (
            settings_composition_path,
            settings_composition_source,
            "language_reader=self.ui_preferences",
        ),
        (
            live_composition_path,
            live_composition_source,
            "language_reader=runtime_settings.language_reader",
        ),
    )
    for path, source, marker in required_markers:
        if marker not in source:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} must wire explicit runtime language-reader ports ({marker})"
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


def _check_raw_capture_flow_stays_post_analysis_only() -> list[str]:
    post_analysis_input_path = (
        VIBESENSOR_DIR / "use_cases" / "run" / "post_analysis_input.py"
    )
    post_analysis_loader_path = (
        VIBESENSOR_DIR / "use_cases" / "run" / "post_analysis_loader.py"
    )
    report_surfaces = [
        *sorted(_python_files(VIBESENSOR_DIR / "use_cases" / "history")),
        *sorted(_python_files(VIBESENSOR_DIR / "adapters" / "pdf")),
    ]
    post_analysis_input_source = _read_text(post_analysis_input_path)
    post_analysis_loader_source = _read_text(post_analysis_loader_path)
    failures: list[str] = []
    if "from .raw_capture_replay import" not in post_analysis_input_source:
        failures.append(
            f"{post_analysis_input_path.relative_to(REPO_ROOT)} must keep raw replay assembly in the post-analysis input path"
        )
    for marker in (
        'getattr(db, "aget_raw_capture_manifest", None)',
        'getattr(db, "aload_raw_capture", None)',
    ):
        if marker not in post_analysis_loader_source:
            failures.append(
                f"{post_analysis_loader_path.relative_to(REPO_ROOT)} must load raw capture through RunPersistence ({marker})"
            )
    forbidden_prefixes = (
        "vibesensor.use_cases.run.raw_capture_replay",
        "vibesensor.use_cases.run.raw_capture_writer",
        "vibesensor.adapters.persistence.history_db._raw_capture_store",
    )
    for path in report_surfaces:
        violations = _imports_from_prefixes(path, forbidden_prefixes)
        if violations:
            failures.append(
                f"{path.relative_to(REPO_ROOT)} must not bypass the post-analysis/raw persistence boundary:\n"
                + "\n".join(violations)
            )
    return failures


_FORBIDDEN_DOMAIN_IMPORTS = (
    "vibesensor.adapters",
    "vibesensor.infra",
    "vibesensor.shared.types",
    "vibesensor.use_cases",
)

_CHECK_DOMAIN_IMPORTS_STAY_INNER = _import_prefix_check(
    paths_provider=lambda: _python_files(VIBESENSOR_DIR / "domain"),
    prefixes=_FORBIDDEN_DOMAIN_IMPORTS,
    failure_template="{path} imports outer packages directly:\n{violations}",
)
