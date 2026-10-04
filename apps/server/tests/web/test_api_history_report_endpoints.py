from __future__ import annotations

from dataclasses import dataclass, field, replace
from io import BytesIO

import pytest
from _history_endpoint_helpers import (
    FakeHistoryDB,
    FakeLiveWs,
    FakeState,
    make_app_and_state,
    make_metadata,
    make_status_app,
    sample,
)
from fastapi.testclient import TestClient
from pypdf import PdfReader
from test_support.analysis import summarize_mappings

from vibesensor.web.router import create_router


def _pdf_text(body: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(body)).pages).lower()


def test_history_insights_returns_persisted_analysis() -> None:
    app, _ = make_app_and_state(language="en")
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/insights")

    assert response.status_code == 200
    result = response.json()
    assert result["lang"] == "en"
    assert "most_likely_origin" in result
    check_keys = {str(item.get("check_key")) for item in result.get("run_suitability", [])}
    assert "SUITABILITY_CHECK_SPEED_VARIATION" in check_keys


def test_report_pdf_respects_lang_query() -> None:
    app, _ = make_app_and_state(language="en")
    with TestClient(app) as client:
        en = client.get("/api/history/run-1/report.pdf", params={"lang": "en"})
        nl = client.get("/api/history/run-1/report.pdf", params={"lang": "nl"})

    assert en.content.startswith(b"%PDF")
    assert nl.content.startswith(b"%PDF")
    assert "vibesensor vibration report" in _pdf_text(en.content)
    assert "vibesensor-trillingsrapport" in _pdf_text(nl.content)


def test_report_pdf_reuses_cached_pdf_for_same_run_lang_and_analysis() -> None:
    call_count = 0

    def fake_renderer(_prepared: object) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-cached"

    app, _ = make_app_and_state(language="en", pdf_renderer=fake_renderer)
    with TestClient(app) as client:
        first = client.get("/api/history/run-1/report.pdf", params={"lang": "en"})
        second = client.get("/api/history/run-1/report.pdf", params={"lang": "en"})

    assert call_count == 1
    assert first.content == second.content == b"%PDF-cached"


def test_report_pdf_cache_invalidates_when_analysis_completed_at_changes() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(20)]
    analysis = summarize_mappings(metadata, samples, lang="en", include_samples=False)

    @dataclass
    class TimestampFlipDB(FakeHistoryDB):
        timestamps: list[str] = field(
            default_factory=lambda: ["2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"]
        )
        idx: int = 0

        def get_run(self, run_id: str):
            result = super().get_run(run_id)
            if result is None:
                return None
            ts = self.timestamps[min(self.idx, len(self.timestamps) - 1)]
            self.idx += 1
            return replace(result, analysis_completed_at=ts)

    call_count = 0

    def fake_renderer(_prepared: object) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-versioned"

    state = FakeState(
        TimestampFlipDB(metadata, samples, analysis),
        FakeLiveWs(),
        pdf_renderer=fake_renderer,
    )
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_router(state))
    with TestClient(app) as client:
        client.get("/api/history/run-1/report.pdf", params={"lang": "en"})
        client.get("/api/history/run-1/report.pdf", params={"lang": "en"})

    assert call_count == 2


@pytest.mark.parametrize(
    ("status", "analysis", "expected_status", "expected_detail"),
    [
        ("analyzing", {"status": "analyzing"}, 409, "Analysis is still in progress"),
        ("error", {"status": "error"}, 422, "Analysis failed"),
        ("complete", None, 422, "No analysis available for this run"),
        (
            "complete",
            {"some_field": 42},
            422,
            "Report data unavailable for this run. Re-analyze to regenerate the PDF.",
        ),
    ],
)
def test_report_pdf_status_and_analysis_errors(
    status: str,
    analysis: dict[str, object] | None,
    expected_status: int,
    expected_detail: str,
) -> None:
    app = make_status_app(status=status, analysis=analysis, include_error_message=True)
    with TestClient(app) as client:
        response = client.get("/api/history/run-1/report.pdf", params={"lang": "en"})

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
