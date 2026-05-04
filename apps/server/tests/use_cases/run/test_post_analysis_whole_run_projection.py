from __future__ import annotations

from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.shared.run_context_warning import RunContextWarning
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.run.post_analysis_whole_run_projection import (
    append_run_context_warnings,
    append_whole_run_analysis_metadata,
    refresh_report_fallback_metadata,
)


def _window_policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=800,
        window_size_samples=2048,
        stride_samples=200,
        overlap_samples=1848,
        feature_interval_s=0.25,
    )


def test_append_whole_run_analysis_metadata_records_sensor_and_artifact_counts() -> None:
    summary = make_persisted_analysis({"analysis_metadata": {}})
    manifest = WholeRunArtifactManifest(
        run_id="run-1",
        relative_dir="whole-run-artifacts/run-1",
        window_policy=_window_policy(),
        total_window_count=4,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-a",
                relative_path="spectra/sensor-a/windows.jsonl",
                file_format="jsonl",
                record_count=4,
                sensor_id="sensor-a",
            ),
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-b",
                relative_path="spectra/sensor-b/windows.jsonl",
                file_format="jsonl",
                record_count=4,
                sensor_id="sensor-b",
            ),
            WholeRunArtifactFile(
                artifact_key="context-labels",
                relative_path="context/window-labels.jsonl",
                file_format="jsonl",
                record_count=4,
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )

    result = append_whole_run_analysis_metadata(summary, manifest).to_json_object()

    assert result["analysis_metadata"] == {
        "whole_run_artifacts_available": True,
        "whole_run_artifacts_status": "available",
        "whole_run_artifact_manifest_path": "whole-run-artifacts/run-1/manifest.json",
        "whole_run_artifact_generated_at": "2025-01-01T00:00:00Z",
        "whole_run_artifact_schema_version": manifest.schema_version,
        "whole_run_artifact_storage_type": manifest.storage_type,
        "whole_run_window_count": 4,
        "whole_run_sensor_count": 2,
        "whole_run_artifact_count": 3,
        "whole_run_artifact_keys": [
            "spectral-summary:sensor-a",
            "spectral-summary:sensor-b",
            "context-labels",
        ],
        "whole_run_artifact_formats": {
            "spectral-summary:sensor-a": "jsonl",
            "spectral-summary:sensor-b": "jsonl",
            "context-labels": "jsonl",
        },
        "whole_run_artifact_paths": {
            "spectral-summary:sensor-a": "spectra/sensor-a/windows.jsonl",
            "spectral-summary:sensor-b": "spectra/sensor-b/windows.jsonl",
            "context-labels": "context/window-labels.jsonl",
        },
        "whole_run_algorithm_versions": {},
        "whole_run_artifact_configuration": {},
        "whole_run_source_raw_manifest_count": 0,
        "whole_run_artifact_warnings": [],
    }


def test_append_run_context_warnings_preserves_existing_warning_rows() -> None:
    summary = make_persisted_analysis(
        {
            "warnings": [
                {
                    "code": "existing",
                    "severity": "warn",
                    "applies_to": "order_analysis",
                    "title": "Existing",
                }
            ]
        }
    )

    result = append_run_context_warnings(
        summary,
        (
            RunContextWarning(
                code="whole_run_alignment_incomplete",
                severity="warn",
                applies_to="whole_run",
                title="Whole-run warning",
                detail="Incomplete alignment",
            ),
        ),
    ).to_json_object()

    assert result["warnings"] == [
        {
            "code": "existing",
            "severity": "warn",
            "applies_to": "order_analysis",
            "title": "Existing",
        },
        {
            "code": "whole_run_alignment_incomplete",
            "severity": "warn",
            "applies_to": "whole_run",
            "title": "Whole-run warning",
            "detail": "Incomplete alignment",
        },
    ]


def test_refresh_report_fallback_metadata_clears_reason_when_diagnosis_summary_exists() -> None:
    summary = make_persisted_analysis(
        {
            "run_id": "run-1",
            "analysis_metadata": {
                "raw_capture_mode": "raw_backed",
                "raw_backed_sample_count": 24,
                "fallback_reasons": ["whole_run_evidence_missing"],
                "whole_run_diagnosis_summaries_available": True,
                "whole_run_diagnosis_summary_count": 1,
            },
            "whole_run_diagnosis_summaries": [
                {
                    "diagnosis_key": "wheel_1x",
                    "suspected_source": "wheel/tire",
                    "rank": 1,
                    "data_basis": "raw_backed",
                    "ambiguous_diagnosis": False,
                    "ambiguous_location": False,
                    "suspicious": False,
                    "weak_spatial_separation": False,
                    "has_reference_gap": False,
                    "uses_summary_fallback": False,
                    "exemplar_references": [],
                    "support_factors": [],
                    "counterevidence_factors": [],
                }
            ],
        }
    )

    result = refresh_report_fallback_metadata(summary).to_json_object()

    assert "fallback_reasons" not in result["analysis_metadata"]
