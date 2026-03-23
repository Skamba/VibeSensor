"""Tests for the HTTP API OpenAPI schema export utility."""

from __future__ import annotations

import json
from typing import Any

import pytest
from _paths import REPO_ROOT

from vibesensor.cli.http_api_schema_export import export_schema


@pytest.fixture(scope="module")
def schema_text() -> str:
    return export_schema()


@pytest.fixture(scope="module")
def schema_dict(schema_text: str) -> dict[str, Any]:
    return json.loads(schema_text)


def test_export_schema_returns_valid_openapi_document(schema_dict: dict[str, Any]) -> None:
    assert schema_dict["openapi"].startswith("3.")
    assert "/api/health" in schema_dict["paths"]
    assert "components" in schema_dict


def test_export_schema_ends_with_newline(schema_text: str) -> None:
    assert schema_text.endswith("\n")


def test_export_schema_writes_to_file(tmp_path) -> None:
    out = tmp_path / "http_api_schema.json"
    text = export_schema(out_path=out)
    assert out.exists()
    assert out.read_text(encoding="utf-8") == text


def test_export_schema_matches_committed_schema(schema_text: str) -> None:
    committed_path = REPO_ROOT / "apps" / "ui" / "src" / "contracts" / "http_api_schema.json"
    assert committed_path.exists(), (
        f"Committed UI contract file is missing: {committed_path}. "
        "Normal repo test runs require checked-in UI contract artifacts."
    )
    committed = committed_path.read_text(encoding="utf-8")
    assert committed == schema_text, (
        "Committed http_api_schema.json is out of sync with generated schema. "
        "Run 'python -m vibesensor.cli.http_api_schema_export' and commit the result."
    )


def test_export_schema_contains_typed_history_list_entry(schema_dict: dict[str, Any]) -> None:
    history_response = schema_dict["components"]["schemas"]["HistoryListResponse"]
    assert history_response["properties"]["runs"]["items"] == {
        "$ref": "#/components/schemas/HistoryListEntryResponse",
    }


def test_export_schema_contains_finding_components_for_history_insights(
    schema_dict: dict[str, Any],
) -> None:
    history_insights_route = schema_dict["paths"]["/api/history/{run_id}/insights"]["get"]
    history_insights = schema_dict["components"]["schemas"]["HistoryInsightsResponse"]
    analyzing_response = schema_dict["components"]["schemas"]["HistoryInsightsAnalyzingResponse"]
    finding_payload = schema_dict["components"]["schemas"]["FindingPayload"]

    assert history_insights_route["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HistoryInsightsResponse",
    }
    assert history_insights_route["responses"]["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HistoryInsightsAnalyzingResponse",
    }
    assert analyzing_response["required"] == ["run_id", "status"]
    assert history_insights["properties"]["findings"]["items"] == {
        "$ref": "#/components/schemas/FindingPayload",
    }
    assert history_insights["properties"]["top_causes"]["items"] == {
        "$ref": "#/components/schemas/FindingPayload",
    }
    assert history_insights["properties"]["warnings"]["items"] == {
        "$ref": "#/components/schemas/HistoryInsightWarningResponse",
    }
    assert history_insights["properties"]["sensor_intensity_by_location"]["items"] == {
        "$ref": "#/components/schemas/LocationIntensitySummaryResponse",
    }
    assert {
        "finding_id",
        "suspected_source",
        "amplitude_metric",
        "evidence_metrics",
        "matched_points",
    }.issubset(finding_payload["properties"])
    assert {
        "quick_checks",
        "peak_speed_kmh",
        "speed_window_kmh",
        "localization_confidence",
        "corroborating_locations",
        "next_sensor_move",
        "actions",
        "phase_presence",
        "grouped_count",
        "diagnostic_caveat",
    }.isdisjoint(finding_payload["properties"])
    assert finding_payload["properties"]["evidence_metrics"]["anyOf"] == [
        {"$ref": "#/components/schemas/FindingEvidenceMetrics"},
        {"type": "null"},
    ]
    assert finding_payload["properties"]["matched_points"]["items"] == {
        "$ref": "#/components/schemas/MatchedPoint",
    }


def test_export_schema_contains_typed_analysis_summary_for_history_run(
    schema_dict: dict[str, Any],
) -> None:
    history_run = schema_dict["components"]["schemas"]["HistoryRunResponse"]
    analysis_summary = schema_dict["components"]["schemas"]["AnalysisSummaryResponse"]
    finding_payload = schema_dict["components"]["schemas"]["FindingPayload"]
    car_gearbox = schema_dict["components"]["schemas"]["CarLibraryGearboxEntry"]
    plot_data = schema_dict["components"]["schemas"]["PlotDataResult"]

    assert history_run["properties"]["analysis"]["anyOf"] == [
        {"$ref": "#/components/schemas/AnalysisSummaryResponse"},
        {"type": "null"},
    ]
    assert history_run["additionalProperties"] is False
    assert history_run["properties"]["sample_count"]["type"] == "integer"
    assert analysis_summary["additionalProperties"] is False
    assert finding_payload["additionalProperties"] is False
    assert analysis_summary["properties"]["case_id"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert analysis_summary["properties"]["report_date"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert analysis_summary["properties"]["fft_window_size_samples"]["anyOf"] == [
        {"type": "integer"},
        {"type": "null"},
    ]
    assert car_gearbox["additionalProperties"] is False
    assert car_gearbox["properties"]["gear_ratios"]["anyOf"] == [
        {
            "items": {"type": "number"},
            "minItems": 1,
            "type": "array",
        },
        {"type": "null"},
    ]
    assert analysis_summary["properties"]["findings"]["items"] == {
        "$ref": "#/components/schemas/FindingPayload",
    }
    assert analysis_summary["properties"]["top_causes"]["items"] == {
        "$ref": "#/components/schemas/FindingPayload",
    }
    assert analysis_summary["properties"]["speed_breakdown"]["items"] == {
        "$ref": "#/components/schemas/SpeedBreakdownRow",
    }
    assert analysis_summary["properties"]["phase_speed_breakdown"]["items"] == {
        "$ref": "#/components/schemas/PhaseSpeedBreakdownRow",
    }
    assert analysis_summary["properties"]["warnings"]["items"] == {
        "$ref": "#/components/schemas/SummaryWarningResponse",
    }
    assert analysis_summary["properties"]["phase_segments"]["items"] == {
        "$ref": "#/components/schemas/PhaseSegmentSummaryResponse",
    }
    assert analysis_summary["properties"]["test_plan"]["items"] == {
        "$ref": "#/components/schemas/TestPlanStepResponse",
    }
    assert analysis_summary["properties"]["phase_timeline"]["items"] == {
        "$ref": "#/components/schemas/PhaseTimelineEntryResponse",
    }
    assert analysis_summary["properties"]["speed_stats"] == {
        "$ref": "#/components/schemas/SpeedStatsResponse",
    }
    assert analysis_summary["properties"]["speed_stats_by_phase"]["additionalProperties"] == {
        "$ref": "#/components/schemas/SpeedStatsResponse",
    }
    assert analysis_summary["properties"]["phase_info"] == {
        "$ref": "#/components/schemas/PhaseInfoResponse",
    }
    assert analysis_summary["properties"]["sensor_intensity_by_location"]["items"] == {
        "$ref": "#/components/schemas/LocationIntensitySummaryResponse",
    }
    assert analysis_summary["properties"]["data_quality"] == {
        "$ref": "#/components/schemas/DataQualityResponse",
    }
    assert analysis_summary["properties"]["run_suitability"]["items"] == {
        "$ref": "#/components/schemas/RunSuitabilityCheck",
    }
    assert analysis_summary["properties"]["plots"]["anyOf"] == [
        {"$ref": "#/components/schemas/PlotDataResult"},
        {"type": "null"},
    ]
    assert plot_data["properties"]["peaks_table"]["items"] == {
        "$ref": "#/components/schemas/PeakTableRow",
    }
    assert plot_data["properties"]["peaks_spectrogram"] == {
        "$ref": "#/components/schemas/SpectrogramResult",
    }
    assert plot_data["properties"]["peaks_spectrogram_raw"] == {
        "$ref": "#/components/schemas/SpectrogramResult",
    }


def test_export_schema_uses_snake_case_settings_contract_fields(
    schema_dict: dict[str, Any],
) -> None:
    active_car_request = schema_dict["components"]["schemas"]["ActiveCarRequest"]
    cars_response = schema_dict["components"]["schemas"]["CarsResponse"]
    sensors_response = schema_dict["components"]["schemas"]["SensorsResponse"]
    speed_source_request = schema_dict["components"]["schemas"]["SpeedSourceRequest"]
    speed_source_response = schema_dict["components"]["schemas"]["SpeedSourceResponse"]
    speed_unit_request = schema_dict["components"]["schemas"]["SpeedUnitRequest"]
    speed_unit_response = schema_dict["components"]["schemas"]["SpeedUnitResponse"]

    assert "car_id" in active_car_request["properties"]
    assert "carId" not in active_car_request["properties"]
    assert "active_car_id" in cars_response["properties"]
    assert "activeCarId" not in cars_response["properties"]
    assert "sensors_by_mac" in sensors_response["properties"]
    assert "sensorsByMac" not in sensors_response["properties"]
    assert {"speed_source", "manual_speed_kph", "stale_timeout_s"} == set(
        speed_source_request["properties"],
    )
    assert {"speed_source", "manual_speed_kph", "stale_timeout_s"} == set(
        speed_source_response["properties"],
    )
    assert "speed_unit" in speed_unit_request["properties"]
    assert "speedUnit" not in speed_unit_request["properties"]
    assert "speed_unit" in speed_unit_response["properties"]
    assert "speedUnit" not in speed_unit_response["properties"]
