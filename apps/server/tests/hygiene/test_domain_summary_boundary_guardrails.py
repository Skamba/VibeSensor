"""Guardrails for summary and boundary modules around domain objects."""

from __future__ import annotations


def test_boundary_decoder_builds_diagnostic_case_from_summary() -> None:
    from test_support.findings import make_finding_payload

    from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
        diagnostic_case_from_summary,
    )

    summary = {
        "case_id": "summary-case-guard-id",
        "run_id": "summary-case-guard",
        "metadata": {
            "run_id": "summary-case-guard",
            "active_car_snapshot": {"name": "Guard Car", "type": "sedan"},
        },
        "findings": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "top_causes": [make_finding_payload(finding_id="F001", confidence=0.80)],
        "test_plan": [
            {
                "action_id": "check-wheel",
                "what": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHAT"},
                "why": {"_i18n_key": "ACTION_WHEEL_BALANCE_WHY"},
            }
        ],
    }
    diagnostic_case = diagnostic_case_from_summary(summary)
    assert diagnostic_case.case_id == "summary-case-guard-id"
    assert diagnostic_case.test_runs
    assert diagnostic_case.primary_run is not None


def test_shared_type_modules_use_focused_history_and_settings_owners() -> None:
    """Run/history and settings contracts must stay in focused shared type modules."""
    from tests._paths import SERVER_ROOT

    shared_types_dir = SERVER_ROOT / "vibesensor" / "shared" / "types"
    run_schema_source = (shared_types_dir / "run_schema.py").read_text()
    history_records_source = (shared_types_dir / "history_records.py").read_text()
    settings_snapshot_source = (shared_types_dir / "settings_snapshot.py").read_text()

    assert not (shared_types_dir / "backend_types.py").exists()
    assert "class RunMetadata" in run_schema_source
    assert "class HistoryRunListEntry" in history_records_source
    assert "class StoredHistoryRun" in history_records_source
    assert "class SettingsSnapshotPayload" in settings_snapshot_source


def test_summary_serialization_package_hides_internal_build_context() -> None:
    from vibesensor.shared.boundaries import summary_serialization

    assert not hasattr(summary_serialization, "AnalysisSummaryBuildContext")
    assert not hasattr(summary_serialization, "build_summary_payload")


def test_diagnostics_modules_do_not_import_analysis_view_contracts() -> None:
    from tests._paths import SERVER_ROOT

    diagnostics_dir = SERVER_ROOT / "vibesensor" / "use_cases" / "diagnostics"
    offenders: list[str] = []
    for path in diagnostics_dir.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "vibesensor.shared.types.analysis_views" in source:
            offenders.append(str(path.relative_to(SERVER_ROOT)))

    assert not offenders, (
        "Diagnostics internals should keep using local view dataclasses and boundary "
        f"serializers instead of importing shared analysis_views contracts directly: {offenders}"
    )
