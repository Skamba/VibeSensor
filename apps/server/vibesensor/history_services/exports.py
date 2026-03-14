"""CSV/ZIP export shaping and streaming for history runs."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeGuard

from ..backend_types import HistoryRunPayload
from ..boundaries.diagnostic_case import project_summary_through_domain
from ..json_types import JsonObject, JsonValue, is_json_object
from ..json_utils import sanitize_for_json
from .helpers import async_require_run, safe_filename, strip_internal_fields

if TYPE_CHECKING:
    from ..history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

EXPORT_BATCH_SIZE = 2048
EXPORT_SPOOL_THRESHOLD = 4 * 1024 * 1024
EXPORT_STREAM_CHUNK = 1024 * 1024

EXPORT_CSV_COLUMNS: tuple[str, ...] = (
    "run_id",
    "timestamp_utc",
    "t_s",
    "client_id",
    "client_name",
    "location",
    "sample_rate_hz",
    "speed_kmh",
    "gps_speed_kmh",
    "speed_source",
    "engine_rpm",
    "engine_rpm_source",
    "gear",
    "final_drive_ratio",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
    "dominant_freq_hz",
    "dominant_axis",
    "top_peaks",
    "vibration_strength_db",
    "strength_bucket",
    "strength_peak_amp_g",
    "strength_floor_amp_g",
    "frames_dropped_total",
    "queue_overflow_drops",
)

EXPORT_CSV_COLUMN_SET: frozenset[str] = frozenset(EXPORT_CSV_COLUMNS)
CsvCell = str | int | float | None
CsvRow = dict[str, CsvCell]


def _is_json_value(value: object) -> TypeGuard[JsonValue]:
    return value is None or isinstance(value, (bool, int, float, str, list, dict))


def flatten_for_csv(row: JsonObject) -> CsvRow:
    """Convert nested/complex values to JSON strings for CSV export."""
    out: CsvRow = {}
    for key, value in row.items():
        if key in EXPORT_CSV_COLUMN_SET:
            out[key] = (
                json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            )
    return out


@dataclass
class HistoryExportDownload:
    """Streaming ZIP export with filename and size metadata."""

    filename: str
    file_size: int
    spool: tempfile.SpooledTemporaryFile[bytes]
    chunk_size: int = EXPORT_STREAM_CHUNK

    def iter_bytes(self) -> Iterator[bytes]:
        try:
            while True:
                chunk = self.spool.read(self.chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            self.spool.close()


class HistoryExportService:
    """Build ZIP exports for history runs without route-local business logic."""

    __slots__ = ("_history_db",)

    def __init__(self, history_db: HistoryDB) -> None:
        self._history_db = history_db

    async def build_export(self, run_id: str) -> HistoryExportDownload:
        run = await async_require_run(self._history_db, run_id)
        spool = await asyncio.to_thread(self._build_zip_file, run, run_id)
        file_size = spool.seek(0, 2)
        spool.seek(0)
        return HistoryExportDownload(
            filename=f"{safe_filename(run_id)}.zip",
            file_size=file_size,
            spool=spool,
        )

    def _build_zip_file(
        self,
        run: HistoryRunPayload,
        run_id: str,
    ) -> tempfile.SpooledTemporaryFile[bytes]:
        sample_count = 0
        safe_name = safe_filename(run_id)
        spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
            max_size=EXPORT_SPOOL_THRESHOLD,
        )
        try:
            with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                with archive.open(f"{safe_name}_raw.csv", mode="w") as raw_csv:
                    raw_csv_text = io.TextIOWrapper(raw_csv, encoding="utf-8", newline="")
                    writer = csv.DictWriter(
                        raw_csv_text,
                        fieldnames=EXPORT_CSV_COLUMNS,
                        extrasaction="ignore",
                    )
                    writer.writeheader()
                    for batch in self._history_db.iter_run_samples(
                        run_id,
                        batch_size=EXPORT_BATCH_SIZE,
                    ):
                        sample_count += len(batch)
                        writer.writerows(flatten_for_csv(row) for row in batch)
                    raw_csv_text.flush()

                archive.writestr(
                    f"{safe_name}.json",
                    build_run_details_json(run, sample_count, run_id),
                )

            spool.seek(0)
        except BaseException:
            spool.close()
            raise
        return spool


def build_run_details_json(
    run: HistoryRunPayload,
    sample_count: int,
    run_id: str,
) -> str:
    """Build the exported JSON metadata document for a history run."""
    run_details: JsonObject = {}
    for key, value in run.items():
        if _is_json_value(value):
            run_details[key] = value
    run_details["sample_count"] = sample_count
    analysis = run_details.get("analysis")
    if is_json_object(analysis):
        run_details["analysis"] = strip_internal_fields(project_summary_through_domain(analysis))
    sanitized, had_non_finite = sanitize_for_json(run_details)
    if had_non_finite:
        LOGGER.warning("Export run %s: sanitized non-finite floats in analysis data", run_id)
    return json.dumps(
        sanitized,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
