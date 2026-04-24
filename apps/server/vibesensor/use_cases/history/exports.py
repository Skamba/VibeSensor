"""CSV/ZIP export shaping and streaming for history runs."""

from __future__ import annotations

import csv
import io
import logging
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass

from vibesensor.shared.boundaries.sensor_frames import sensor_frame_to_json_object
from vibesensor.shared.filenames import safe_filename
from vibesensor.shared.json_utils import json_text_dumps, sanitize_for_json
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.history_records import StoredHistoryRun
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.history.helpers import async_require_run

LOGGER = logging.getLogger(__name__)

EXPORT_BATCH_SIZE = 2048
EXPORT_SPOOL_THRESHOLD = 4 * 1024 * 1024
EXPORT_STREAM_CHUNK = 1024 * 1024

EXPORT_CSV_COLUMNS: tuple[str, ...] = (
    "run_id",
    "timestamp_utc",
    "t_s",
    "analysis_window_start_us",
    "analysis_window_end_us",
    "analysis_window_synced",
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


def flatten_for_csv(row: JsonObject) -> CsvRow:
    """Convert nested/complex values to JSON strings for CSV export."""
    out: CsvRow = {}
    for key, value in row.items():
        if key in EXPORT_CSV_COLUMN_SET:
            out[key] = json_text_dumps(value) if isinstance(value, (dict, list)) else value
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


@dataclass
class HistoryExportContext:
    """Raw export artifacts ready for adapter-level packaging."""

    run_id: str
    safe_name: str
    run: StoredHistoryRun
    sample_count: int
    raw_csv_spool: tempfile.SpooledTemporaryFile[bytes]


class HistoryExportService:
    """Load raw export artifacts for history runs without delivery-layer shaping."""

    __slots__ = ("_history_db",)

    def __init__(self, history_db: RunPersistence) -> None:
        self._history_db = history_db

    async def build_export_context(self, run_id: str) -> HistoryExportContext:
        run = await async_require_run(self._history_db, run_id)
        raw_csv_spool, sample_count = await self._build_raw_csv_spool(run_id)
        return HistoryExportContext(
            run_id=run_id,
            safe_name=safe_filename(run_id),
            run=run,
            sample_count=sample_count,
            raw_csv_spool=raw_csv_spool,
        )

    async def _build_raw_csv_spool(
        self,
        run_id: str,
    ) -> tuple[tempfile.SpooledTemporaryFile[bytes], int]:
        sample_count = 0
        spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
            max_size=EXPORT_SPOOL_THRESHOLD,
        )
        spool_built = False
        try:
            raw_csv_text = io.TextIOWrapper(spool, encoding="utf-8", newline="")
            writer = csv.DictWriter(
                raw_csv_text,
                fieldnames=EXPORT_CSV_COLUMNS,
                extrasaction="ignore",
            )
            writer.writeheader()
            async for batch in self._history_db.aiter_run_samples(
                run_id,
                batch_size=EXPORT_BATCH_SIZE,
            ):
                sample_count += len(batch)
                writer.writerows(flatten_for_csv(sensor_frame_to_json_object(row)) for row in batch)
            raw_csv_text.flush()
            raw_csv_text.detach()
            spool.seek(0)
            spool_built = True
        finally:
            if not spool_built:
                spool.close()
        return spool, sample_count


def serialize_run_details_json(run_details: JsonObject, *, sample_count: int, run_id: str) -> str:
    run_details["sample_count"] = sample_count
    sanitized, had_non_finite = sanitize_for_json(run_details)
    if had_non_finite:
        LOGGER.warning("Export run %s: sanitized non-finite floats in analysis data", run_id)
    return json_text_dumps(
        sanitized,
        indent=2,
        sort_keys=True,
    )
