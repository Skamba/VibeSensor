"""Backend static guard orchestration."""

from __future__ import annotations

from collections.abc import Callable
from .analysis_report_checks import (
    _CHECK_ANALYSIS_AND_HISTORY_CORE_DO_NOT_IMPORT_PDF_ADAPTER,
    _CHECK_LIVE_SURFACES_DO_NOT_IMPORT_POST_RUN_CONCLUSIONS,
    _CHECK_SERVER_HAS_NO_LOCAL_VIBRATION_STRENGTH_MODULE,
    _CHECK_USE_CASES_DO_NOT_IMPORT_ADAPTERS_DIRECTLY,
    _check_analysis_modules_do_not_import_i18n,
    _check_backend_tests_do_not_use_source_introspection,
    _check_canonical_dataflow_doc,
    _check_external_modules_use_analysis_public_api,
    _check_fft_analysis_is_centralized,
    _check_live_processing_does_not_import_analysis,
    _check_metrics_log_reads_live_start_under_lock,
    _check_recording_flow_uses_flush_and_persistence_writer,
    _check_report_modules_do_not_import_analysis,
    _check_report_modules_use_shared_strength_math,
    _check_strength_metric_definition_is_centralized,
    _check_ui_code_does_not_compute_strength_metrics,
)
from .adapters_http_checks import (
    _CHECK_DOMAIN_IMPORTS_STAY_INNER,
    _CHECK_ROUTE_FACING_HTTP_MODULES_AVOID_INFRA_IMPORTS,
    _check_analysis_summary_stays_at_boundaries,
    _check_clients_http_adapter_uses_protocol_dependencies,
    _check_health_snapshot_moves_out_of_http_adapter,
    _check_history_report_loader_avoids_analysis_dict_rewrap,
    _check_history_services_do_not_import_httpexception,
    _check_http_route_modules_stay_split_and_focused,
    _check_modules_avoid_diagnostics_facade_reexports,
    _check_raw_capture_flow_stays_post_analysis_only,
    _check_report_pdf_entrypoint_renders_report_document,
    _check_runtime_settings_use_explicit_reader_ports,
    _check_sensor_metadata_writes_stay_in_settings_boundary,
    _check_settings_services_use_shared_update_helper,
    _check_summary_payload_uses_build_context,
    _check_ws_broadcast_uses_projection_module,
)
from .type_safety_checks import (
    _CHECK_BACKEND_TYPES_MODULE_REMOVED,
    _CHECK_SHARED_TYPES_DO_NOT_IMPORT_FROM_INFRA,
    _check_boundary_and_report_modules_do_not_import_analysis_coordinator,
    _check_diagnostics_boundary_types,
    _check_diagnostics_core_types_stay_core_only,
    _check_domain_modules_do_not_import_analysis_coordinator,
    _check_domain_package_has_no_payload_type_imports,
    _check_domain_vos_have_no_dict_accepting_factory_methods,
    _check_http_api_models_live_under_http_adapters,
    _check_isolated_server_runtime_owner,
    _check_new_domain_modules_keep_import_isolation,
    _check_planning_service_has_no_payload_imports,
    _check_post_analysis_uses_suitability_check,
    _check_root_module_allowlist,
    _check_run_analysis_does_not_define_normalize_lang,
    _check_run_context_split_owners,
    _check_settings_snapshot_boundary_location,
    _check_shared_constants_package_split,
    _check_shared_types_no_domain_factory_methods,
    _check_suspected_vibration_origin_is_boundary_only,
    _check_types_modules_do_not_duplicate_domain_concepts_as_typeddicts,
    _check_updates_package_subpackages,
)
from .domain_boundary_checks import (
    _CHECK_DOMAIN_IMPORT_DIRECTION,
    _check_boundaries_do_not_import_analysis,
    _check_boundaries_do_not_import_outer_layers,
    _check_boundary_owns_no_meaning_finding_kind,
    _check_boundary_owns_no_meaning_vibration_source,
    _check_domain_and_use_cases_do_not_import_car_config,
    _check_domain_and_use_cases_do_not_read_raw_aspects_dict_keys,
    _check_domain_code_does_not_access_raw_tire_fields,
    _check_domain_does_not_import_outer_packages,
    _check_finding_stays_run_scoped,
    _check_run_capture_uses_run_id_boundary,
    _check_run_lifecycle_only,
    _check_run_status_from_domain_only,
    _check_signature_confinement,
)
from .legacy_removal_checks import (
    _CHECK_PROCESS_SETTINGS_SHIM_REMOVED,
    _CHECK_SETTINGS_FACADE_REMOVED,
    _check_history_db_facade_removed,
    _check_settings_snapshot_legacy_decode_removed,
    _check_static_data_uses_packaged_tree_only,
    _check_udp_hello_legacy_compat_removed,
    _check_update_status_legacy_decode_removed,
)

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
    ("FFT analysis stays centralized", _check_fft_analysis_is_centralized),
    (
        "No local diagnostics vibration_strength module exists",
        _CHECK_SERVER_HAS_NO_LOCAL_VIBRATION_STRENGTH_MODULE,
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
        "Use cases avoid importing adapters directly",
        _CHECK_USE_CASES_DO_NOT_IMPORT_ADAPTERS_DIRECTLY,
    ),
    (
        "Analysis/history core avoids direct PDF adapter imports",
        _CHECK_ANALYSIS_AND_HISTORY_CORE_DO_NOT_IMPORT_PDF_ADAPTER,
    ),
    (
        "Live telemetry avoids post-run conclusion modules",
        _CHECK_LIVE_SURFACES_DO_NOT_IMPORT_POST_RUN_CONCLUSIONS,
    ),
    ("Canonical dataflow doc stays complete", _check_canonical_dataflow_doc),
    (
        "Recording flow uses sample flush and persistence writer",
        _check_recording_flow_uses_flush_and_persistence_writer,
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
        _CHECK_ROUTE_FACING_HTTP_MODULES_AVOID_INFRA_IMPORTS,
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
    (
        "Raw capture flow stays in post-analysis boundaries",
        _check_raw_capture_flow_stays_post_analysis_only,
    ),
    ("Domain modules avoid outer-layer imports", _CHECK_DOMAIN_IMPORTS_STAY_INNER),
    (
        "New domain modules keep import isolation",
        _check_new_domain_modules_keep_import_isolation,
    ),
    (
        "backend_types catch-all module stays removed",
        _CHECK_BACKEND_TYPES_MODULE_REMOVED,
    ),
    (
        "Shared backend types avoid infra imports",
        _CHECK_SHARED_TYPES_DO_NOT_IMPORT_FROM_INFRA,
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
        "Isolated server runtime stays out of shared",
        _check_isolated_server_runtime_owner,
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
    ("Domain import direction stays inward", _CHECK_DOMAIN_IMPORT_DIRECTION),
    ("Finding stays run-scoped", _check_finding_stays_run_scoped),
    ("RunCapture uses run_id boundary", _check_run_capture_uses_run_id_boundary),
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
    (
        "Process settings shim stays removed",
        _CHECK_PROCESS_SETTINGS_SHIM_REMOVED,
    ),
    (
        "Settings facade stays removed",
        _CHECK_SETTINGS_FACADE_REMOVED,
    ),
    (
        "HistoryDB facade stays removed",
        _check_history_db_facade_removed,
    ),
    (
        "Updater status legacy decode stays removed",
        _check_update_status_legacy_decode_removed,
    ),
    (
        "Settings snapshot legacy decode stays removed",
        _check_settings_snapshot_legacy_decode_removed,
    ),
    (
        "UDP HELLO legacy compatibility stays removed",
        _check_udp_hello_legacy_compat_removed,
    ),
    (
        "Static data uses packaged tree only",
        _check_static_data_uses_packaged_tree_only,
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
