from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiosqlite

from vibesensor.adapters.history import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)
from vibesensor.adapters.http.dependencies import (
    HistoryDeps,
    HistoryExportServiceProtocol,
    HistoryReportServiceProtocol,
    HistoryRunServiceProtocol,
)
from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)
from vibesensor.app.config_schema import AppConfig
from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.ports import SettingsReader
from vibesensor.use_cases.history.exports import HistoryExportService
from vibesensor.use_cases.history.reports import HistoryReportService
from vibesensor.use_cases.history.runs import HistoryRunService

LOGGER = logging.getLogger(__name__)


class HistoryAdapterFactory(Protocol):
    def __call__(
        self,
        db_path: Path,
        *,
        corruption_reporter: Callable[[str], None] | None = None,
        engine_failure_reporter: Callable[[str, str], None] | None = None,
    ) -> HistoryPersistenceAdapters: ...


@dataclass(frozen=True, slots=True)
class HistoryServiceBundle:
    """History and reporting services derived from shared persistence adapters."""

    run_service: HistoryRunServiceProtocol
    report_service: HistoryReportServiceProtocol
    export_service: HistoryExportServiceProtocol

    def http_deps(self) -> HistoryDeps:
        """Return the focused HTTP history dependency group."""

        return HistoryDeps(
            run_service=self.run_service,
            report_service=self.report_service,
            export_service=self.export_service,
        )


def _build_prepared_pdf_bytes(prepared: PreparedReportInput) -> bytes:
    """Render a prepared report input through the PDF adapter boundary."""
    from vibesensor.adapters.pdf.pdf_engine import build_prepared_report_pdf

    return build_prepared_report_pdf(prepared)


def create_history_db(
    config: AppConfig,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
    engine_failure_reporter: Callable[[str, str], None] | None = None,
    adapter_factory: HistoryAdapterFactory = create_history_persistence_adapters,
) -> HistoryPersistenceAdapters:
    """Create and initialise the shared history persistence collaborators."""
    history = adapter_factory(
        config.logging.history_db_path,
        corruption_reporter=corruption_reporter,
        engine_failure_reporter=engine_failure_reporter,
    )
    if history.lifecycle.corruption_detected:
        LOGGER.error(
            "History DB corruption detected at startup; skipping stale-run recovery, "
            "retention pruning, and "
            "continuing with writes disabled until the DB is repaired.",
        )
        return history
    try:
        recovered_runs = history.run_repository.recover_stale_recording_runs()
    except (aiosqlite.Error, OSError):
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history.lifecycle.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)
    raw_capture_retention_days = config.logging.raw_capture_retention_days
    summary_retention_days = config.logging.run_retention_days
    if raw_capture_retention_days < summary_retention_days:
        try:
            pruned_raw_captures = (
                history.run_repository.prune_raw_capture_artifacts_older_than_days(
                    raw_capture_retention_days,
                )
            )
        except (aiosqlite.Error, OSError):
            LOGGER.warning(
                "Failed to prune raw capture artifacts older than %d day(s) during "
                "startup maintenance",
                raw_capture_retention_days,
                exc_info=True,
            )
        else:
            if pruned_raw_captures:
                LOGGER.info(
                    "Pruned raw capture artifacts for %d terminal run(s) older than %d "
                    "day(s); summary retention remains %d day(s)",
                    pruned_raw_captures,
                    raw_capture_retention_days,
                    summary_retention_days,
                )
    try:
        pruned_runs = history.run_repository.prune_terminal_runs_older_than_days(
            summary_retention_days,
        )
    except (aiosqlite.Error, OSError):
        LOGGER.warning(
            "Failed to prune terminal runs older than %d day(s) during startup maintenance",
            summary_retention_days,
            exc_info=True,
        )
    else:
        if pruned_runs:
            LOGGER.info(
                "Pruned %d terminal run(s) older than %d day(s) during startup maintenance",
                pruned_runs,
                summary_retention_days,
            )
    return history


def build_history_service_bundle(
    *,
    history: HistoryPersistenceAdapters,
    current_car_reader: SettingsReader,
) -> HistoryServiceBundle:
    """Build the focused history/reporting services over shared persistence."""

    history_run_service = HistoryRunService(history.run_repository)
    history_export_service = HistoryExportService(history.run_repository)
    return HistoryServiceBundle(
        run_service=ProjectedHistoryRunService(
            history_run_service,
            current_car_reader=current_car_reader,
        ),
        report_service=HistoryReportService(
            history.run_repository,
            pdf_renderer=_build_prepared_pdf_bytes,
        ),
        export_service=ProjectedHistoryExportService(history_export_service),
    )
