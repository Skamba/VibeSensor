"""CSV/ZIP export shaping and streaming for history runs."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from vibesensor.common.filenames import safe_filename
from vibesensor.common.json_types import JsonObject
from vibesensor.common.json_utils import json_text_dumps, sanitize_for_json
from vibesensor.common.time_utils import parse_iso8601
from vibesensor.history.helpers import async_require_run
from vibesensor.history.records import StoredHistoryRun
from vibesensor.recording.sensor_frame_mapping import sensor_frame_to_json_object

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB
    from vibesensor.recording.sensor_frame import SensorFrame

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
    """Export artifacts ready for adapter-level packaging.

    ``windows_csv_spool`` holds one row per stored analysis window (``sample_count``
    rows); ``raw_capture_files`` are the run's raw accelerometer capture and its
    manifest. Spools that outgrow memory go to ``spool_dir`` (the data directory,
    not a RAM-backed ``/tmp``).
    """

    run_id: str
    safe_name: str
    run: StoredHistoryRun
    sample_count: int
    windows_csv_spool: tempfile.SpooledTemporaryFile[bytes]
    raw_capture_files: tuple[Path, ...]
    spool_dir: Path


class HistoryExportService:
    """Load raw export artifacts for history runs without delivery-layer shaping."""

    __slots__ = ("_history_db",)

    def __init__(self, history_db: HistoryDB) -> None:
        self._history_db = history_db

    async def build_export_context(self, run_id: str) -> HistoryExportContext:
        run = await async_require_run(self._history_db, run_id)
        spool_dir = self._history_db.db_path.parent
        windows_csv_spool, sample_count = await asyncio.to_thread(
            self._build_windows_csv_spool, run, spool_dir
        )
        raw_capture_files = await asyncio.to_thread(self._history_db.raw_capture_files, run_id)
        return HistoryExportContext(
            run_id=run_id,
            safe_name=safe_filename(run_id),
            run=run,
            sample_count=sample_count,
            windows_csv_spool=windows_csv_spool,
            raw_capture_files=raw_capture_files,
            spool_dir=spool_dir,
        )

    def _build_windows_csv_spool(
        self,
        run: StoredHistoryRun,
        spool_dir: Path,
    ) -> tuple[tempfile.SpooledTemporaryFile[bytes], int]:
        sample_count = 0
        time_base = _sample_time_base(run)
        spool: tempfile.SpooledTemporaryFile[bytes] = tempfile.SpooledTemporaryFile(
            max_size=EXPORT_SPOOL_THRESHOLD,
            dir=str(spool_dir),
        )
        spool_built = False
        try:
            csv_text = io.TextIOWrapper(spool, encoding="utf-8", newline="")
            writer = csv.DictWriter(
                csv_text,
                fieldnames=EXPORT_CSV_COLUMNS,
                extrasaction="ignore",
            )
            writer.writeheader()
            for batch in self._history_db.iter_run_samples(
                run.run_id,
                batch_size=EXPORT_BATCH_SIZE,
            ):
                sample_count += len(batch)
                writer.writerows(_csv_row(row, time_base) for row in batch)
            csv_text.flush()
            csv_text.detach()
            spool.seek(0)
            spool_built = True
        finally:
            if not spool_built:
                spool.close()
        return spool, sample_count


def _sample_time_base(run: StoredHistoryRun) -> datetime | None:
    """The start to re-time a run's sample rows from, when they were stamped on a wrong clock.

    A run that started before the Pi clock was set stamped its rows with that
    clock (or, after an NTP step mid-run, partly with the right one), and a
    correction moves only the run's own times. Start plus each row's ``t_s``
    (monotonic seconds since that start) puts every row on the run's clock.
    ``None`` for a run started on a trusted clock: its rows are right as stored.
    """
    metadata = run.metadata
    if not metadata.start_time_unverified and metadata.start_time_corrected_by_s is None:
        return None
    return parse_iso8601(run.start_time_utc)


def _csv_row(frame: SensorFrame, time_base: datetime | None) -> CsvRow:
    row = flatten_for_csv(sensor_frame_to_json_object(frame))
    if time_base is not None and frame.t_s is not None:
        row["timestamp_utc"] = (time_base + timedelta(seconds=frame.t_s)).isoformat()
    return row


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
