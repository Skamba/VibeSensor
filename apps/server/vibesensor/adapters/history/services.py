"""History delivery services that apply projection at the boundary."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from typing import cast

from pydantic import TypeAdapter

from vibesensor.adapters.http.models import (
    DeleteHistoryRunResponse,
    HistoryInsightsResponse,
    HistoryListEntryResponse,
    HistoryRunResponse,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.summary_fields.warnings import localize_warning_list
from vibesensor.shared.ports import ActiveCarReader
from vibesensor.shared.types.json_types import JsonValue, is_json_array, is_json_object
from vibesensor.use_cases.history.exports import (
    EXPORT_SPOOL_THRESHOLD,
    HistoryExportContext,
    HistoryExportDownload,
    HistoryExportService,
)
from vibesensor.use_cases.history.runs import HistoryRunService
from vibesensor.use_cases.run.run_context import add_current_context_warnings

from .projection import (
    build_projected_run_details_json,
    project_history_insights,
    project_history_run_record,
)

_HISTORY_INSIGHTS_ADAPTER = TypeAdapter(HistoryInsightsResponse)

__all__ = ["ProjectedHistoryExportService", "ProjectedHistoryRunService"]


class ProjectedHistoryRunService:
    """Adapter that projects persisted history analysis before HTTP delivery."""

    __slots__ = ("_current_car_reader", "_service")

    def __init__(
        self,
        service: HistoryRunService,
        current_car_reader: ActiveCarReader | None = None,
    ) -> None:
        self._service = service
        self._current_car_reader = current_car_reader

    async def list_runs(self) -> list[HistoryListEntryResponse]:
        return [
            HistoryListEntryResponse.model_validate(entry.to_json_object())
            for entry in await self._service.list_runs()
        ]

    async def get_run(self, run_id: str) -> HistoryRunResponse:
        return HistoryRunResponse.model_validate(
            project_history_run_record(await self._service.get_run(run_id))
        )

    async def get_insights(
        self,
        run_id: str,
        requested_lang: str | None = None,
    ) -> HistoryInsightsResponse | None:
        result = await self._service.get_insights(run_id, requested_lang=requested_lang)
        if result is None:
            return None
        projected = project_history_insights(result)
        if self._current_car_reader is not None:
            raw_warnings = projected.get("warnings")
            raw_metadata = projected.get("metadata")
            typed_metadata = (
                run_metadata_from_mapping(raw_metadata) if is_json_object(raw_metadata) else None
            )
            overlay_warnings = add_current_context_warnings(
                raw_warnings if is_json_array(raw_warnings) else None,
                metadata=typed_metadata,
                current_active_car_snapshot=self._current_car_reader.active_car_snapshot(),
            )
            projected["warnings"] = cast(
                JsonValue,
                localize_warning_list(
                    overlay_warnings,
                    lang=str(requested_lang or projected.get("lang") or "en"),
                ),
            )
        validated = _HISTORY_INSIGHTS_ADAPTER.validate_python(projected)
        return cast(
            HistoryInsightsResponse,
            _HISTORY_INSIGHTS_ADAPTER.dump_python(validated, mode="json"),
        )

    async def delete_run(self, run_id: str) -> DeleteHistoryRunResponse:
        return DeleteHistoryRunResponse.model_validate(await self._service.delete_run(run_id))


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
        download_built = False
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
            download_built = True
            return HistoryExportDownload(
                filename=f"{context.safe_name}.zip",
                file_size=file_size,
                spool=spool,
            )
        finally:
            if not download_built:
                spool.close()
            context.raw_csv_spool.close()
