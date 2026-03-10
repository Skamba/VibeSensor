"""Thin HTTP routes for history CRUD, insights, report download, and exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..api_models import (
    DeleteHistoryRunResponse,
    HistoryInsightsResponse,
    HistoryListResponse,
    HistoryRunResponse,
)
from ._helpers import domain_errors_to_http

if TYPE_CHECKING:
    from ..runtime.state import RuntimePersistenceSubsystem


def create_history_routes(
    persistence: RuntimePersistenceSubsystem,
) -> APIRouter:
    """Create and return the run-history / report API routes."""
    router = APIRouter()
    run_service = persistence.run_service
    report_service = persistence.report_service
    export_service = persistence.export_service

    # -- history CRUD ----------------------------------------------------------

    @router.get("/api/history", response_model=HistoryListResponse)
    async def get_history() -> HistoryListResponse:
        return HistoryListResponse(runs=await run_service.list_runs())

    @router.get("/api/history/{run_id}", response_model=HistoryRunResponse)
    async def get_history_run(run_id: str) -> HistoryRunResponse:
        with domain_errors_to_http():
            return HistoryRunResponse(**await run_service.get_run(run_id))

    @router.get("/api/history/{run_id}/insights", response_model=HistoryInsightsResponse)
    async def get_history_insights(
        run_id: str,
        lang: str | None = Query(default=None),
    ) -> HistoryInsightsResponse | JSONResponse:
        with domain_errors_to_http():
            result = await run_service.get_insights(run_id, requested_lang=lang)
        if result is None:
            return JSONResponse(
                status_code=202,
                content={"run_id": run_id, "status": "analyzing"},
            )
        return HistoryInsightsResponse(**result)

    @router.delete("/api/history/{run_id}", response_model=DeleteHistoryRunResponse)
    async def delete_history_run(run_id: str) -> DeleteHistoryRunResponse:
        with domain_errors_to_http():
            return DeleteHistoryRunResponse(**await run_service.delete_run(run_id))

    # -- report PDF ------------------------------------------------------------

    @router.get("/api/history/{run_id}/report.pdf", response_class=Response)
    async def download_history_report_pdf(
        run_id: str,
        lang: str | None = Query(default=None),
    ) -> Response:
        with domain_errors_to_http():
            pdf = await report_service.build_pdf(run_id, lang)
        pdf_headers = {
            "Content-Disposition": f'attachment; filename="{pdf.filename}"',
        }
        return Response(
            content=pdf.content,
            media_type="application/pdf",
            headers=pdf_headers,
        )

    # -- CSV/ZIP export --------------------------------------------------------

    @router.get("/api/history/{run_id}/export", response_class=StreamingResponse)
    async def export_history_run(run_id: str) -> StreamingResponse:
        with domain_errors_to_http():
            export = await export_service.build_export(run_id)
        return StreamingResponse(
            content=export.iter_bytes(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{export.filename}"',
                "Content-Length": str(export.file_size),
            },
        )

    return router
