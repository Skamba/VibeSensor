"""Runtime helpers for the RunRecorder orchestration loop."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.constants import NUMERIC_TYPES
from vibesensor.shared.ports import ClientTracker, SettingsReader
from vibesensor.shared.time_utils import utc_now_iso

if TYPE_CHECKING:
    from .logger import RunRecorder

__all__ = [
    "active_frames_total",
    "analysis_settings_snapshot",
    "normalize_accel_scale_g_per_lsb",
    "run_loop",
]

_DB_THREAD_TIMEOUT_S = 10.0
_DB_TIMEOUT_ERROR = "metrics logger DB call timed out"
_TICK_FAILURE_PREFIX = "metrics logger tick failed: "


def normalize_accel_scale_g_per_lsb(value: object) -> float | None:
    """Return a positive accel scale or ``None`` when the input is unusable."""
    return float(value) if isinstance(value, NUMERIC_TYPES) and value > 0 else None


def analysis_settings_snapshot(
    settings_store: SettingsReader | None,
) -> AnalysisSettingsSnapshot:
    """Load the current analysis settings snapshot or repo defaults."""
    if settings_store is not None:
        return settings_store.analysis_settings_snapshot()
    return AnalysisSettingsSnapshot.from_dict(AnalysisSettingsSnapshot.DEFAULTS)


def active_frames_total(registry: ClientTracker) -> int:
    """Return the total active frame count across all connected clients."""
    _get = registry.get
    return sum(
        int(record.frames_total)
        for client_id in registry.active_client_ids()
        if (record := _get(client_id)) is not None
    )


def _is_tick_error_message(message: str | None) -> bool:
    return message == _DB_TIMEOUT_ERROR or bool(
        message and message.startswith(_TICK_FAILURE_PREFIX),
    )


async def run_loop(recorder: RunRecorder, *, logger: logging.Logger) -> None:
    """Drive the periodic live-sample flush loop for ``RunRecorder``."""
    interval = 1.0 / recorder.metrics_log_hz
    while True:
        try:
            with recorder._lock:
                live_start = recorder._live_start_mono_s
                snapshot = recorder._session_snapshot()
            if snapshot is None:
                if _is_tick_error_message(recorder._persistence.last_write_error):
                    recorder._persistence.clear_last_write_error()
                await asyncio.sleep(interval)
                continue
            timestamp_utc = utc_now_iso()
            live_rows = await asyncio.wait_for(
                asyncio.to_thread(
                    recorder._sample_flush.build_sample_records,
                    run_id=snapshot.run_id,
                    t_s=max(0.0, time.monotonic() - live_start),
                    timestamp_utc=timestamp_utc,
                ),
                timeout=_DB_THREAD_TIMEOUT_S,
            )
            if not isinstance(live_rows, list):
                logger.warning(
                    "Metrics logger sample builder returned %s instead of list; dropping tick.",
                    type(live_rows).__name__,
                )
                live_rows = []
            no_data_timeout = await asyncio.wait_for(
                asyncio.to_thread(
                    recorder._sample_flush.append_records,
                    snapshot.run_id,
                    snapshot.start_time_utc,
                    snapshot.start_mono_s,
                    prebuilt_rows=live_rows,
                ),
                timeout=_DB_THREAD_TIMEOUT_S,
            )
            if no_data_timeout:
                logger.info(
                    "Auto-stopping run %s after %.1fs without new data",
                    snapshot.run_id,
                    recorder._lifecycle.no_data_timeout_s,
                )
                recorder.stop_recording(_only_if_run_id=snapshot.run_id)
            if _is_tick_error_message(recorder._persistence.last_write_error):
                recorder._persistence.clear_last_write_error()
        except TimeoutError:
            recorder._persistence.set_last_write_error(_DB_TIMEOUT_ERROR)
            logger.warning(
                "Metrics logger DB call exceeded %.1fs timeout; skipping tick.",
                _DB_THREAD_TIMEOUT_S,
            )
        except Exception as exc:
            recorder._persistence.set_last_write_error(f"{_TICK_FAILURE_PREFIX}{exc}")
            logger.warning(
                "Metrics logger tick failed; will retry next interval.",
                exc_info=True,
            )
        await asyncio.sleep(interval)
