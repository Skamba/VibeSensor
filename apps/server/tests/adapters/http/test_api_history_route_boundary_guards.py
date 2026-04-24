from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.http.error_boundary import install_http_exception_handlers
from vibesensor.adapters.http.history import create_history_routes
from vibesensor.adapters.http.middleware import install_request_logging_middleware
from vibesensor.shared.filenames import safe_filename
from vibesensor.use_cases.history.reports import HistoryReportPdf


@dataclass
class _FakeExportDownload:
    filename: str
    file_size: int = 7
    payload: bytes = b"payload"

    def iter_bytes(self):
        yield self.payload


def _history_test_client() -> tuple[TestClient, MagicMock, MagicMock, MagicMock]:
    run_service = MagicMock()
    run_service.get_run = AsyncMock(return_value={"run_id": "run-1"})
    run_service.get_insights = AsyncMock(return_value={"run_id": "run-1", "status": "complete"})
    run_service.delete_run = AsyncMock(return_value={"run_id": "run-1", "deleted": True})

    report_service = MagicMock()
    report_service.build_pdf = AsyncMock(
        return_value=HistoryReportPdf(content=b"%PDF-safe", filename="run-1_report.pdf")
    )

    export_service = MagicMock()
    export_service.build_export = AsyncMock(return_value=_FakeExportDownload(filename="run-1.zip"))

    app = FastAPI()
    install_http_exception_handlers(app)
    install_request_logging_middleware(app)
    app.include_router(
        create_history_routes(
            run_service=run_service,
            report_service=report_service,
            export_service=export_service,
        )
    )
    return (
        TestClient(app, raise_server_exceptions=False),
        run_service,
        report_service,
        export_service,
    )


@pytest.mark.parametrize(
    ("method", "path", "failing_attr"),
    [
        ("GET", "/api/history/run-1", "get_run"),
        ("GET", "/api/history/run-1/insights", "get_insights"),
        ("DELETE", "/api/history/run-1", "delete_run"),
        ("GET", "/api/history/run-1/report.pdf", "build_pdf"),
        ("GET", "/api/history/run-1/export", "build_export"),
    ],
)
def test_history_routes_return_sanitized_json_for_unexpected_service_failures(
    method: str,
    path: str,
    failing_attr: str,
) -> None:
    client, run_service, report_service, export_service = _history_test_client()
    getattr(
        {
            "get_run": run_service,
            "get_insights": run_service,
            "delete_run": run_service,
            "build_pdf": report_service,
            "build_export": export_service,
        }[failing_attr],
        failing_attr,
    ).side_effect = RuntimeError("sensitive failure detail")

    response = client.request(method, path)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Internal Server Error"}
    assert "sensitive failure detail" not in response.text


@pytest.mark.parametrize(
    ("path", "failing_attr", "malicious_filename", "expected_header"),
    [
        (
            "/api/history/run-1/report.pdf",
            "build_pdf",
            "bad\r\nX-Injected: yes.pdf",
            'attachment; filename="bad__X-Injected__yes.pdf"',
        ),
        (
            "/api/history/run-1/export",
            "build_export",
            "bad\r\nX-Injected: yes.zip",
            'attachment; filename="bad__X-Injected__yes.zip"',
        ),
    ],
)
def test_history_download_routes_sanitize_content_disposition_filenames(
    path: str,
    failing_attr: str,
    malicious_filename: str,
    expected_header: str,
) -> None:
    client, _run_service, report_service, export_service = _history_test_client()
    if failing_attr == "build_pdf":
        report_service.build_pdf = AsyncMock(
            return_value=HistoryReportPdf(content=b"%PDF-safe", filename=malicious_filename)
        )
    else:
        export_service.build_export = AsyncMock(
            return_value=_FakeExportDownload(filename=malicious_filename)
        )

    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == expected_header
    assert safe_filename(malicious_filename) in response.headers["content-disposition"]
    assert "\r" not in response.headers["content-disposition"]
    assert "\n" not in response.headers["content-disposition"]
