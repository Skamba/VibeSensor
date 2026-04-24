from __future__ import annotations

from dataclasses import dataclass, field, replace
from io import BytesIO

import pytest
from _history_endpoint_helpers import (
    FakeHistoryDB,
    FakeState,
    FakeWsHub,
    _real_pdf_renderer,
    make_metadata,
    make_router_and_state,
    make_status_router,
    response_payload,
    route_endpoint,
    sample,
)
from fastapi import FastAPI, HTTPException
from pypdf import PdfReader
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.adapters.http import create_router
from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary


def _pdf_text(body: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(body)).pages).lower()


@pytest.mark.asyncio
async def test_history_insights_returns_persisted_analysis() -> None:
    router, _ = make_router_and_state(language="en")
    endpoint = route_endpoint(router, "/api/history/{run_id}/insights")
    result = response_payload(await endpoint("run-1"))
    assert result["lang"] == "en"
    assert "most_likely_origin" in result
    check_keys = {str(item.get("check_key")) for item in result.get("run_suitability", [])}
    assert "SUITABILITY_CHECK_SPEED_VARIATION" in check_keys


@pytest.mark.asyncio
async def test_report_pdf_respects_lang_query() -> None:
    router, _ = make_router_and_state(language="en")
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")
    en = await endpoint("run-1", "en")
    nl = await endpoint("run-1", "nl")
    assert en.body.startswith(b"%PDF")
    assert nl.body.startswith(b"%PDF")
    assert en.body == nl.body


@pytest.mark.asyncio
async def test_report_pdf_respects_lang_query_with_persisted_report_template_data() -> None:
    router, state = make_router_and_state(language="nl")
    state.history_db.analysis["_report_template_data"] = {"lang": "nl", "title": "legacy"}
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")

    nl = await endpoint("run-1", "nl")
    en = await endpoint("run-1", "en")

    assert nl.body.startswith(b"%PDF")
    assert en.body.startswith(b"%PDF")

    nl_text = _pdf_text(nl.body)
    text_from_en_request = _pdf_text(en.body)
    assert "vibesensor-diagnoserapport" in nl_text
    assert "vibesensor-diagnoserapport" in text_from_en_request
    assert "diagnostic worksheet" not in text_from_en_request


@pytest.mark.asyncio
async def test_report_pdf_lang_override_when_template_data_persisted() -> None:
    metadata = make_metadata(language="nl")
    samples = [sample(i) for i in range(20)]
    analysis = summarize_run_data(metadata, samples, lang="nl", include_samples=False)
    analysis["_report_template_data"] = {"lang": "nl", "title": "legacy"}

    render_count = 0
    real_renderer = _real_pdf_renderer

    def counting_renderer(prepared: object) -> bytes:
        nonlocal render_count
        render_count += 1
        return real_renderer(prepared)

    db = FakeHistoryDB(metadata, samples, analysis)
    state = FakeState(db, FakeWsHub(), pdf_renderer=counting_renderer)
    app = FastAPI()
    router = create_router(state)
    app.include_router(router)
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")

    nl = await endpoint("run-1", "nl")
    en = await endpoint("run-1", "en")

    assert render_count == 1

    assert nl.body.startswith(b"%PDF")
    assert en.body.startswith(b"%PDF")
    nl_text = _pdf_text(nl.body)
    text_from_en_request = _pdf_text(en.body)
    assert "vibesensor-diagnoserapport" in nl_text
    assert "vibesensor-diagnoserapport" in text_from_en_request
    assert "diagnostic worksheet" not in text_from_en_request


@pytest.mark.asyncio
async def test_report_pdf_reuses_cached_pdf_for_same_run_lang_and_analysis() -> None:
    call_count = 0

    def fake_renderer(_prepared: object) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-cached"

    router, _ = make_router_and_state(language="en", pdf_renderer=fake_renderer)
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")

    first = await endpoint("run-1", "en")
    second = await endpoint("run-1", "en")

    assert call_count == 1
    assert first.body == second.body == b"%PDF-cached"


@pytest.mark.asyncio
async def test_report_pdf_reuses_cached_pdf_across_lang_when_template_is_persisted() -> None:
    call_count = 0

    def fake_renderer(_prepared: object) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-cached-cross-lang"

    router, state = make_router_and_state(language="nl", pdf_renderer=fake_renderer)
    state.history_db.analysis["_report_template_data"] = {"lang": "nl", "title": "legacy"}
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")

    first = await endpoint("run-1", "en")
    second = await endpoint("run-1", "nl")

    assert call_count == 1
    assert first.body == second.body == b"%PDF-cached-cross-lang"


@pytest.mark.asyncio
async def test_report_pdf_cache_invalidates_when_analysis_completed_at_changes() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(20)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    analysis["_report_template_data"] = {"lang": "en", "title": "legacy"}

    @dataclass
    class TimestampFlipDB(FakeHistoryDB):
        timestamps: list[str] = field(
            default_factory=lambda: ["2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"]
        )
        idx: int = 0

        async def aget_run(self, run_id: str):
            result = await super().aget_run(run_id)
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
        TimestampFlipDB(metadata, samples, analysis), FakeWsHub(), pdf_renderer=fake_renderer
    )
    router = create_router(state)
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")

    await endpoint("run-1", "en")
    await endpoint("run-1", "en")

    assert call_count == 2


@pytest.mark.asyncio
async def test_report_pdf_cache_invalidates_when_analysis_content_changes() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(20)]
    first_analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    first_analysis["_report_template_data"] = {"lang": "en", "title": "legacy"}
    second_analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    second_analysis["_report_template_data"] = {"lang": "en", "title": "updated"}

    @dataclass
    class AnalysisFlipDB(FakeHistoryDB):
        analyses: list[AnalysisSummary] = field(default_factory=list)
        idx: int = 0

        async def aget_run(self, run_id: str):
            result = await super().aget_run(run_id)
            if result is None:
                return None
            analysis = self.analyses[min(self.idx, len(self.analyses) - 1)]
            self.idx += 1
            return replace(result, analysis=make_persisted_analysis(analysis))

    call_count = 0

    def fake_renderer(_prepared: object) -> bytes:
        nonlocal call_count
        call_count += 1
        return b"%PDF-analysis-versioned"

    state = FakeState(
        AnalysisFlipDB(
            metadata,
            samples,
            first_analysis,
            analyses=[first_analysis, second_analysis],
        ),
        FakeWsHub(),
        pdf_renderer=fake_renderer,
    )
    router = create_router(state)
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")

    await endpoint("run-1", "en")
    await endpoint("run-1", "en")

    assert call_count == 2


@pytest.mark.asyncio
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
async def test_report_pdf_status_and_analysis_errors(
    status: str,
    analysis: dict[str, object] | None,
    expected_status: int,
    expected_detail: str,
) -> None:
    router = make_status_router(status=status, analysis=analysis, include_error_message=True)
    endpoint = route_endpoint(router, "/api/history/{run_id}/report.pdf")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint("run-1", "en")
    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
