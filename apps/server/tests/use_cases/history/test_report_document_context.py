from __future__ import annotations

from test_support.findings import make_finding_payload

from vibesensor.shared.boundaries.reporting import PreparedReportInput, prepare_report_input
from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.use_cases.history import report_document
from vibesensor.use_cases.history.report_document.composition import compose_report_document


def _prepared_report_input() -> PreparedReportInput:
    finding = make_finding_payload(finding_id="F001")
    return prepare_report_input(
        {
            "run_id": "report-context",
            "file_name": "report-context.csv",
            "rows": 32,
            "duration_s": 12.5,
            "sensor_count_used": 2,
            "lang": "en",
            "metadata": {},
            "report_date": "",
            "record_length": "",
            "start_time_utc": "",
            "end_time_utc": "",
            "warnings": [],
            "sensor_locations": ["front-left", "rear-right"],
            "sensor_locations_connected_throughout": ["rear-right"],
            "sensor_intensity_by_location": [],
            "most_likely_origin": {},
            "run_suitability": [],
            "plots": {},
            "test_plan": [],
            "findings": [finding],
            "top_causes": [finding],
        }
    )


def test_compose_report_document_returns_canonical_document() -> None:
    prepared = _prepared_report_input()

    document = compose_report_document(prepared)

    assert isinstance(document, ReportDocument)
    assert document.sensor_locations == ["rear-right"]
    assert document == report_document.build_report_document(prepared)
