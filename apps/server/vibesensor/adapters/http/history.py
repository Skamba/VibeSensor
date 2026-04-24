"""Thin HTTP routes for history CRUD, insights, report download, and exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from vibesensor.adapters.http._helpers import (
    OpenAPIResponses,
    normalize_run_id_or_400,
    safe_filename,
)
from vibesensor.adapters.http.error_boundary import route_errors_to_http
from vibesensor.adapters.http.models import (
    DeleteHistoryRunResponse,
    HistoryInsightsAnalyzingResponse,
    HistoryInsightsResponse,
    HistoryListResponse,
    HistoryRunResponse,
)

if TYPE_CHECKING:
    from vibesensor.adapters.http.dependencies import (
        HistoryExportServiceProtocol,
        HistoryReportServiceProtocol,
        HistoryRunServiceProtocol,
    )

_RUN_NOT_FOUND_RESPONSE: OpenAPIResponses = {
    404: {"description": "Requested run was not found."},
}

_INVALID_RUN_ID_RESPONSE: OpenAPIResponses = {
    400: {"description": "Invalid run identifier."},
}

_RUN_LOAD_ERROR_RESPONSE: OpenAPIResponses = {
    500: {"description": "Run data is corrupt or could not be processed."},
}

_HISTORY_INSIGHTS_RESPONSES: OpenAPIResponses = {
    202: {
        "model": HistoryInsightsAnalyzingResponse,
        "description": "Analysis is still running for the requested run.",
    },
    404: {"description": "Requested run was not found."},
    409: {"description": "Insights are not ready yet for the requested run."},
    422: {
        "description": (
            "Insights are unavailable because analysis failed or produced "
            "unsupported persisted data."
        )
    },
    500: {"description": "Run data is corrupt or insights generation failed."},
}

_REPORT_RESPONSES: OpenAPIResponses = {
    404: {"description": "Requested run was not found."},
    500: {"description": "Report generation failed because the run data is corrupt or incomplete."},
}

_EXPORT_RESPONSES: OpenAPIResponses = {
    404: {"description": "Requested run was not found."},
    500: {"description": "Export generation failed because the run data is corrupt or incomplete."},
}


def create_history_routes(
    *,
    run_service: HistoryRunServiceProtocol,
    report_service: HistoryReportServiceProtocol,
    export_service: HistoryExportServiceProtocol,
) -> APIRouter:
    """Create and return the run-history / report API routes."""
    router = APIRouter(tags=["history"])

    # -- history CRUD ----------------------------------------------------------

    @router.get("/api/history", response_model=HistoryListResponse)
    async def get_history() -> HistoryListResponse:
        """List all persisted recording runs available in history storage."""
        return HistoryListResponse(runs=await run_service.list_runs())

    @router.get(
        "/api/history/{run_id}",
        response_model=HistoryRunResponse,
        response_model_exclude_unset=True,
        response_model_exclude_none=True,
        responses={
            **_INVALID_RUN_ID_RESPONSE,
            **_RUN_NOT_FOUND_RESPONSE,
            **_RUN_LOAD_ERROR_RESPONSE,
        },
    )
    async def get_history_run(run_id: str) -> HistoryRunResponse:
        """Return full metadata and analysis payloads for a single recorded run."""
        run_id = normalize_run_id_or_400(run_id)
        with route_errors_to_http():
            return await run_service.get_run(run_id)

    @router.get(
        "/api/history/{run_id}/insights",
        response_model=HistoryInsightsResponse,
        responses={**_INVALID_RUN_ID_RESPONSE, **_HISTORY_INSIGHTS_RESPONSES},
    )
    async def get_history_insights(
        run_id: str,
        lang: str | None = Query(
            default=None,
            description=(
                "Optional language override for localized insights text (for example 'en' or 'nl')."
            ),
        ),
    ) -> HistoryInsightsResponse | JSONResponse:
        """Return localized post-analysis findings, or a 202 while analysis is still running."""
        run_id = normalize_run_id_or_400(run_id)
        with route_errors_to_http():
            result = await run_service.get_insights(run_id, requested_lang=lang)
        if result is None:
            analyzing_response = HistoryInsightsAnalyzingResponse(run_id=run_id, status="analyzing")
            return JSONResponse(
                status_code=202,
                content=analyzing_response.model_dump(),
            )
        return result

    @router.delete(
        "/api/history/{run_id}",
        response_model=DeleteHistoryRunResponse,
        responses={**_INVALID_RUN_ID_RESPONSE, **_RUN_NOT_FOUND_RESPONSE},
    )
    async def delete_history_run(run_id: str) -> DeleteHistoryRunResponse:
        """Delete a persisted run and its derived artifacts from history storage."""
        run_id = normalize_run_id_or_400(run_id)
        with route_errors_to_http():
            return await run_service.delete_run(run_id)

    # -- report PDF ------------------------------------------------------------

    @router.get(
        "/api/history/{run_id}/report.pdf",
        response_class=Response,
        responses={**_INVALID_RUN_ID_RESPONSE, **_REPORT_RESPONSES},
    )
    async def download_history_report_pdf(
        run_id: str,
        lang: str | None = Query(
            default=None,
            description=(
                "Optional language override for the generated PDF report "
                "(for example 'en' or 'nl')."
            ),
        ),
    ) -> Response:
        """Build and download the PDF diagnostic report for a persisted run."""
        run_id = normalize_run_id_or_400(run_id)
        with route_errors_to_http():
            pdf = await report_service.build_pdf(run_id, lang)
        pdf_headers = {
            "Content-Disposition": f'attachment; filename="{safe_filename(pdf.filename)}"',
        }
        return Response(
            content=pdf.content,
            media_type="application/pdf",
            headers=pdf_headers,
        )

    # -- CSV/ZIP export --------------------------------------------------------

    @router.get(
        "/api/history/{run_id}/export",
        response_class=StreamingResponse,
        responses={**_INVALID_RUN_ID_RESPONSE, **_EXPORT_RESPONSES},
    )
    async def export_history_run(run_id: str) -> StreamingResponse:
        """Build and stream the ZIP export bundle for a persisted run."""
        run_id = normalize_run_id_or_400(run_id)
        with route_errors_to_http():
            export = await export_service.build_export(run_id)
        return StreamingResponse(
            content=export.iter_bytes(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_filename(export.filename)}"',
                "Content-Length": str(export.file_size),
            },
        )

    return router
