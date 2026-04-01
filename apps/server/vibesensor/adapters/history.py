"""History delivery adapters that re-project persisted summaries at the edge."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from typing import cast

from pydantic import TypeAdapter

from vibesensor.adapters.http.models import (
    DeleteHistoryRunResponse,
    HistoryInsightsResponse,
    HistoryListEntryResponse,
    HistoryRunResponse,
)
from vibesensor.shared.boundaries.analysis_summary_projection import project_persisted_analysis
from vibesensor.shared.boundaries.report_payload_gate import has_projectable_report_payload
from vibesensor.shared.boundaries.summary_warning import localize_warning_list
from vibesensor.shared.ports import ActiveCarReader
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_array
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.exports import (
    EXPORT_SPOOL_THRESHOLD,
    HistoryExportContext,
    HistoryExportDownload,
    HistoryExportService,
    serialize_run_details_json,
)
from vibesensor.use_cases.history.helpers import strip_internal_fields
from vibesensor.use_cases.history.runs import HistoryRunService
from vibesensor.use_cases.run.run_context import (
    add_current_context_warnings,
    apply_legacy_run_context_fields,
    run_context_snapshot_from_metadata,
)

_HISTORY_INSIGHTS_ADAPTER = TypeAdapter(HistoryInsightsResponse)


def _project_history_analysis(
    analysis: PersistedAnalysis | Mapping[str, object],
    *,
    strip_internal: bool,
) -> JsonObject:
    if has_projectable_report_payload(analysis):
        projected, _ = project_persisted_analysis(analysis)
    else:
        projected = cast(JsonObject, {key: value for key, value in analysis.items()})
    if strip_internal:
        projected = strip_internal_fields(projected)
    return projected


def _project_history_metadata(metadata: Mapping[str, object]) -> JsonObject:
    projected = cast(JsonObject, {key: value for key, value in metadata.items()})
    context_snapshot = run_context_snapshot_from_metadata(projected)
    apply_legacy_run_context_fields(projected, context_snapshot=context_snapshot)
    order_reference_spec = context_snapshot.order_reference_spec
    if order_reference_spec is not None and order_reference_spec.supports_wheel_reference:
        projected["tire_circumference_m"] = order_reference_spec.tire_circumference_m
    return projected


def project_history_run_record(run: StoredHistoryRun) -> JsonObject:
    """Project persisted analysis fields in a history run for API responses."""
    payload: JsonObject = {
        "run_id": run.run_id,
        "status": run.status.value,
        "sample_count": run.sample_count,
        "metadata": _project_history_metadata(run.metadata.to_dict()),
    }
    if run.error_message is not None:
        payload["error_message"] = run.error_message
    if run.analysis is not None:
        payload["analysis"] = _project_history_analysis(
            run.analysis,
            strip_internal=True,
        )
    return payload


def project_history_insights(analysis: Mapping[str, object]) -> JsonObject:
    """Project persisted insights payloads for HTTP responses."""
    return _project_history_analysis(analysis, strip_internal=True)


def build_projected_run_details_json(
    run: StoredHistoryRun,
    sample_count: int,
    run_id: str,
) -> str:
    """Build the exported JSON metadata document with canonical projected analysis."""
    payload = run.to_json_object()
    payload["metadata"] = _project_history_metadata(run.metadata.to_dict())
    analysis = run.analysis
    if analysis is None:
        return serialize_run_details_json(
            payload,
            sample_count=sample_count,
            run_id=run_id,
        )
    payload["analysis"] = _project_history_analysis(
        analysis,
        strip_internal=True,
    )
    return serialize_run_details_json(
        payload,
        sample_count=sample_count,
        run_id=run_id,
    )


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
            overlay_warnings = add_current_context_warnings(
                raw_warnings if is_json_array(raw_warnings) else None,
                metadata=projected.get("metadata"),
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
