from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

from vibesensor.adapters.http.dependencies import HistoryDeps
from vibesensor.app.config_schema import AppConfig
from vibesensor.history.exports import HistoryExportService
from vibesensor.history.history_db import HistoryDB
from vibesensor.history.projected_services import (
    ProjectedHistoryExportService,
    ProjectedHistoryRunService,
)
from vibesensor.history.runs import HistoryRunService
from vibesensor.report.input import PreparedReportInput
from vibesensor.report.service import HistoryReportService
from vibesensor.shared.ports import SettingsReader

LOGGER = logging.getLogger(__name__)

RUN_RETENTION_DAYS = 7
"""Terminal runs (and their raw/whole-run sidecars) older than this are pruned at startup."""


def _build_prepared_pdf_bytes(prepared: PreparedReportInput) -> bytes:
    """Render a prepared report input through the PDF adapter boundary."""
    from vibesensor.report.pdf.pdf_engine import build_prepared_report_pdf

    return build_prepared_report_pdf(prepared)


def create_history_db(
    config: AppConfig,
    *,
    corruption_reporter: Callable[[str], None] | None = None,
) -> HistoryDB:
    """Open the history DB and run startup recovery plus retention pruning."""
    history = HistoryDB(
        config.logging.history_db_path,
        corruption_reporter=corruption_reporter,
    )
    if history.corruption_detected:
        LOGGER.error(
            "History DB corruption detected at startup; skipping stale-run recovery, "
            "retention pruning, and "
            "continuing with writes disabled until the DB is repaired.",
        )
        return history
    try:
        recovered_runs = history.recover_stale_recording_runs()
    except (sqlite3.Error, OSError):
        LOGGER.error("Failed during early startup DB operations; closing DB.", exc_info=True)
        history.close()
        raise
    if recovered_runs:
        LOGGER.warning("Recovered %d stale recording run(s) on startup", recovered_runs)
    try:
        pruned_runs = history.prune_terminal_runs_older_than_days(
            RUN_RETENTION_DAYS,
        )
    except (sqlite3.Error, OSError):
        LOGGER.warning(
            "Failed to prune terminal runs older than %d day(s) during startup maintenance",
            RUN_RETENTION_DAYS,
            exc_info=True,
        )
    else:
        if pruned_runs:
            LOGGER.info(
                "Pruned %d terminal run(s) older than %d day(s) during startup maintenance",
                pruned_runs,
                RUN_RETENTION_DAYS,
            )
    return history


def build_history_deps(
    *,
    history: HistoryDB,
    current_car_reader: SettingsReader,
) -> HistoryDeps:
    """Build the history/reporting HTTP services over shared persistence."""

    return HistoryDeps(
        run_service=ProjectedHistoryRunService(
            HistoryRunService(history),
            current_car_reader=current_car_reader,
        ),
        report_service=HistoryReportService(
            history,
            pdf_renderer=_build_prepared_pdf_bytes,
        ),
        export_service=ProjectedHistoryExportService(
            HistoryExportService(history),
        ),
    )
