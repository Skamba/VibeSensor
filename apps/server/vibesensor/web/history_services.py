"""History delivery services that apply projection at the boundary."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from pydantic import TypeAdapter

from vibesensor.common.json_types import JsonObject, JsonValue, is_json_array, is_json_object
from vibesensor.common.time_utils import now_in_time_zone
from vibesensor.history.exports import (
    EXPORT_SPOOL_THRESHOLD,
    HistoryExportContext,
    HistoryExportDownload,
    HistoryExportService,
)
from vibesensor.history.projection import (
    build_projected_run_details_json,
    project_history_insights,
    project_history_run_record,
)
from vibesensor.history.runs import HistoryRunService
from vibesensor.recording.run_context import add_current_context_warnings
from vibesensor.recording.run_metadata import run_metadata_from_mapping
from vibesensor.report.run_quality import (
    failing_suitability_warnings,
    warning_codes_stated_by_checks,
)
from vibesensor.summary.run_context_warning import RunContextWarningsInput
from vibesensor.summary.warning_fields import localize_warning_list
from vibesensor.web.models.history import (
    DeleteHistoryRunResponse,
    HistoryInsightsResponse,
    HistoryListEntryResponse,
    HistoryRunResponse,
)

if TYPE_CHECKING:
    from vibesensor.settings.settings_derivation import SettingsDerivationService

_HISTORY_INSIGHTS_ADAPTER = TypeAdapter(HistoryInsightsResponse)

__all__ = ["ProjectedHistoryExportService", "ProjectedHistoryRunService"]


class ProjectedHistoryRunService:
    """Adapter that projects persisted history analysis before HTTP delivery."""

    __slots__ = ("_current_car_reader", "_service", "_speed_unit")

    def __init__(
        self,
        service: HistoryRunService,
        current_car_reader: SettingsDerivationService | None = None,
        *,
        speed_unit: Callable[[], str] = lambda: "kmh",
    ) -> None:
        self._service = service
        self._current_car_reader = current_car_reader
        # The user's speed unit setting; speeds in the server's texts render in it.
        self._speed_unit = speed_unit

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
        lang = str(requested_lang or result.get("lang") or "en")
        projected = project_history_insights(result)
        raw_warnings = projected.get("warnings")
        warnings: RunContextWarningsInput = raw_warnings if is_json_array(raw_warnings) else None
        if self._current_car_reader is not None:
            raw_metadata = projected.get("metadata")
            typed_metadata = (
                run_metadata_from_mapping(raw_metadata) if is_json_object(raw_metadata) else None
            )
            warnings = add_current_context_warnings(
                warnings,
                metadata=typed_metadata,
                current_active_car_snapshot=self._current_car_reader.active_car_snapshot(),
            )
        projected["warnings"] = cast(
            JsonValue,
            _with_suitability_warnings(
                localize_warning_list(warnings, lang=lang),
                projected.get("run_suitability"),
                lang=lang,
                electric=_is_electric_run(projected),
                speed_unit=self._speed_unit(),
            ),
        )
        validated = _HISTORY_INSIGHTS_ADAPTER.validate_python(projected)
        return cast(
            HistoryInsightsResponse,
            _HISTORY_INSIGHTS_ADAPTER.dump_python(validated, mode="json"),
        )

    async def delete_run(self, run_id: str) -> DeleteHistoryRunResponse:
        return DeleteHistoryRunResponse.model_validate(await self._service.delete_run(run_id))


def _is_electric_run(insights: JsonObject) -> bool:
    """Whether the run's diagnosis was for a battery-electric car (as the PDF decides)."""
    diagnosis = insights.get("diagnosis")
    conditions = diagnosis.get("conditions") if is_json_object(diagnosis) else None
    return is_json_object(conditions) and conditions.get("fuel_type") == "EV"


def _with_suitability_warnings(
    warnings: list[JsonObject],
    run_suitability: JsonValue,
    *,
    lang: str,
    electric: bool,
    speed_unit: str,
) -> list[JsonObject]:
    """Lead with the failing run-suitability checks, worded as on the PDF quality page.

    A warning that a failing check already states in full is dropped, as on the PDF.
    """
    rows = run_suitability if is_json_array(run_suitability) else []
    checks = [check for check in rows if is_json_object(check)]
    stated = warning_codes_stated_by_checks(checks)
    return [
        *cast(
            list[JsonObject],
            failing_suitability_warnings(lang, checks, electric=electric, speed_unit=speed_unit),
        ),
        *(warning for warning in warnings if warning.get("code") not in stated),
    ]


class ProjectedHistoryExportService:
    """Adapter that packages projected history exports for HTTP delivery.

    ZIP entry times have no zone, so they are the export time in the browser's
    zone (*time_zone*, else UTC), never the Pi's local zone or a file's mtime
    (which an unset clock may have stamped).
    """

    __slots__ = ("_service", "_time_zone")

    def __init__(
        self,
        service: HistoryExportService,
        *,
        time_zone: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._service = service
        self._time_zone = time_zone

    async def build_export(self, run_id: str) -> HistoryExportDownload:
        context = await self._service.build_export_context(run_id)
        return await asyncio.to_thread(self._build_export_download, context)

    def _build_export_download(self, context: HistoryExportContext) -> HistoryExportDownload:
        spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
            max_size=EXPORT_SPOOL_THRESHOLD,
            dir=str(context.spool_dir),
        )
        download_built = False
        date_time = now_in_time_zone(self._time_zone()).timetuple()[:6]

        def entry(name: str, file_size: int = 0) -> zipfile.ZipInfo:
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.file_size = file_size
            return info

        try:
            with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                context.windows_csv_spool.seek(0)
                with archive.open(
                    entry(f"{context.safe_name}_analysis_windows.csv"), mode="w"
                ) as windows_csv:
                    shutil.copyfileobj(context.windows_csv_spool, windows_csv)
                for path in context.raw_capture_files:
                    with (
                        path.open("rb") as source,
                        archive.open(
                            entry(f"raw-capture/{path.name}", path.stat().st_size), mode="w"
                        ) as target,
                    ):
                        shutil.copyfileobj(source, target)
                archive.writestr(
                    entry(f"{context.safe_name}.json"),
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
            context.windows_csv_spool.close()
