"""History delivery adapters that re-project persisted summaries at the edge."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.boundaries.analysis_summary_projection import project_analysis_summary
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.history.exports import (
    EXPORT_SPOOL_THRESHOLD,
    HistoryExportContext,
    HistoryExportDownload,
    HistoryExportService,
    build_run_details_json,
    serialize_run_details_json,
)
from vibesensor.use_cases.history.helpers import strip_internal_fields
from vibesensor.use_cases.history.runs import HistoryRunService

if TYPE_CHECKING:
    from vibesensor.domain import TestRun


def _has_projectable_analysis(analysis: Mapping[str, object]) -> bool:
    return isinstance(analysis.get("findings"), list) or isinstance(
        analysis.get("top_causes"), list
    )


def _project_history_analysis(
    analysis: Mapping[str, object],
    *,
    strip_internal: bool,
) -> tuple[JsonObject, TestRun | None]:
    if _has_projectable_analysis(analysis):
        projected, test_run = project_analysis_summary(cast(JsonObject, dict(analysis)))
    else:
        projected = cast(JsonObject, {key: value for key, value in analysis.items()})
        test_run = None
    if strip_internal:
        projected = strip_internal_fields(projected)
    return projected, test_run


def project_history_run_record(run: StoredHistoryRun) -> JsonObject:
    """Project persisted analysis fields in a history run for API responses."""
    payload = run.to_json_object()
    if run.analysis is None:
        return payload
    projected, _ = _project_history_analysis(run.analysis.to_json_object(), strip_internal=True)
    payload["analysis"] = projected
    return payload


def project_history_insights(analysis: Mapping[str, object]) -> JsonObject:
    """Project persisted insights payloads for HTTP responses."""
    projected, _ = _project_history_analysis(analysis, strip_internal=True)
    return projected


def prepare_history_report_analysis(
    analysis: AnalysisSummary,
) -> tuple[AnalysisSummary, TestRun | None]:
    """Project persisted report analysis for PDF rendering without stripping template data."""
    projected, test_run = _project_history_analysis(analysis, strip_internal=False)
    return cast(AnalysisSummary, projected), test_run


def build_projected_run_details_json(
    run: StoredHistoryRun,
    sample_count: int,
    run_id: str,
) -> str:
    """Build the exported JSON metadata document with canonical projected analysis."""
    analysis = run.analysis
    if analysis is None:
        return build_run_details_json(run, sample_count, run_id)
    projected, _ = _project_history_analysis(analysis.to_json_object(), strip_internal=True)
    payload = run.to_json_object()
    payload["analysis"] = projected
    return serialize_run_details_json(
        payload,
        sample_count=sample_count,
        run_id=run_id,
    )


class ProjectedHistoryRunService:
    """Adapter that projects persisted history analysis before HTTP delivery."""

    __slots__ = ("_service",)

    def __init__(self, service: HistoryRunService) -> None:
        self._service = service

    async def list_runs(self) -> list[JsonObject]:
        return [entry.to_json_object() for entry in await self._service.list_runs()]

    async def get_run(self, run_id: str) -> JsonObject:
        return project_history_run_record(await self._service.get_run(run_id))

    async def get_insights(
        self,
        run_id: str,
        requested_lang: str | None = None,
    ) -> JsonObject | None:
        result = await self._service.get_insights(run_id, requested_lang=requested_lang)
        if result is None:
            return None
        return project_history_insights(result)

    async def delete_run(self, run_id: str) -> dict[str, str]:
        return await self._service.delete_run(run_id)


class ProjectedHistoryExportService:
    """Adapter that packages projected history exports for HTTP delivery."""

    __slots__ = ("_service",)

    def __init__(self, service: HistoryExportService) -> None:
        self._service = service

    async def build_export(self, run_id: str) -> HistoryExportDownload:
        context = await self._service.build_export_context(run_id)
        return await asyncio.to_thread(self._build_export_download, context)

    def _build_export_download(self, context: HistoryExportContext) -> HistoryExportDownload:
        spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
            max_size=EXPORT_SPOOL_THRESHOLD,
        )
        try:
            with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                context.raw_csv_spool.seek(0)
                with archive.open(f"{context.safe_name}_raw.csv", mode="w") as raw_csv:
                    shutil.copyfileobj(context.raw_csv_spool, raw_csv)
                archive.writestr(
                    f"{context.safe_name}.json",
                    build_projected_run_details_json(
                        context.run,
                        sample_count=context.sample_count,
                        run_id=context.run_id,
                    ),
                )
            file_size = spool.seek(0, 2)
            spool.seek(0)
            return HistoryExportDownload(
                filename=f"{context.safe_name}.zip",
                file_size=file_size,
                spool=spool,
            )
        except BaseException:
            spool.close()
            raise
        finally:
            context.raw_csv_spool.close()
