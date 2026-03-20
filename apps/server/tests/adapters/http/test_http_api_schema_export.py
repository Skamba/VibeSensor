"""Tests for the HTTP API OpenAPI schema export utility."""

from __future__ import annotations

import json
from typing import Any

import pytest
from _paths import SERVER_ROOT

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
    committed_path = (
        SERVER_ROOT.parent / "apps" / "ui" / "src" / "contracts" / "http_api_schema.json"
    )
    if not committed_path.exists():
        pytest.skip("UI contracts not available")
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
    history_insights = schema_dict["components"]["schemas"]["HistoryInsightsResponse"]
    finding_payload = schema_dict["components"]["schemas"]["FindingPayload"]

    assert history_insights["properties"]["findings"]["items"] == {
        "$ref": "#/components/schemas/FindingPayload",
    }
    assert history_insights["properties"]["top_causes"]["items"] == {
        "$ref": "#/components/schemas/FindingPayload",
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
