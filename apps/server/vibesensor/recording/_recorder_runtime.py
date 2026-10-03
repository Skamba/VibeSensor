"""Runtime helpers for the RunRecorder orchestration loop."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from vibesensor.common.time_utils import utc_now_iso
from vibesensor.common.type_checks import NUMERIC_TYPES
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.settings.analysis_settings_codec import (
    analysis_settings_snapshot_from_mapping,
)

if TYPE_CHECKING:
    from vibesensor.ingest.registry import ClientRegistry
    from vibesensor.recording.lifecycle_state import AutoStopReason
    from vibesensor.recording.recorder import RunRecorder
    from vibesensor.settings.settings_derivation import SettingsDerivationService

__all__ = [
    "active_frames_total",
    "analysis_settings_snapshot",
    "normalize_accel_scale_g_per_lsb",
    "flush_active_run_tick",
    "run_loop",
]

_DB_THREAD_TIMEOUT_S = 10.0
_DB_TIMEOUT_ERROR = "metrics logger DB call timed out"
_TICK_FAILURE_PREFIX = "metrics logger tick failed: "


def normalize_accel_scale_g_per_lsb(value: object) -> float | None:
    """Return a positive accel scale or ``None`` when the input is unusable."""
    return float(value) if isinstance(value, NUMERIC_TYPES) and value > 0 else None


def analysis_settings_snapshot(
    settings_reader: SettingsDerivationService | None,
) -> AnalysisSettingsSnapshot:
    """Load the current analysis settings snapshot or repo defaults."""
    if settings_reader is not None:
        return settings_reader.analysis_settings_snapshot()
    return analysis_settings_snapshot_from_mapping(AnalysisSettingsSnapshot.DEFAULTS)


def active_frames_total(registry: ClientRegistry) -> int:
    """Return the total active frame count across all connected clients."""
    _get = registry.get
    return sum(
        int(record.frames_total)
        for client_id in registry.active_client_ids()
        if (record := _get(client_id)) is not None
    )


def _is_tick_error_message(message: str | None) -> bool:
    """Return whether a write error came from the periodic runtime tick path."""
    return message == _DB_TIMEOUT_ERROR or bool(
        message and message.startswith(_TICK_FAILURE_PREFIX),
    )


def flush_active_run_tick(
    recorder: RunRecorder,
    *,
    logger: logging.Logger,
) -> tuple[str | None, AutoStopReason | None]:
    """Flush one active-run tick without holding the recorder lock during I/O-heavy work."""
    with recorder._lock:
        snapshot = recorder._lifecycle.snapshot()
        if snapshot is None:
            return None, None
        live_start_mono_s = recorder._recording_session.live_start_mono_s
    timestamp_utc = utc_now_iso()
    live_rows = recorder._sample_flush.build_sample_records(
        run_id=snapshot.run_id,
        t_s=max(0.0, time.monotonic() - live_start_mono_s),
        timestamp_utc=timestamp_utc,
        run_start_mono_s=live_start_mono_s,
    )
    if not isinstance(live_rows, list):
        logger.warning(
            "Metrics logger sample builder returned %s instead of list; dropping tick.",
            type(live_rows).__name__,
        )
        live_rows = []
    auto_stop_reason = recorder._sample_flush.append_records(
        snapshot.run_id,
        snapshot.start_time_utc,
        live_start_mono_s,
        prebuilt_rows=live_rows,
    )
    return snapshot.run_id, auto_stop_reason


async def run_loop(recorder: RunRecorder, *, logger: logging.Logger) -> None:
    """Drive the periodic live-sample flush loop for ``RunRecorder``."""
    interval = 1.0 / recorder.metrics_log_hz
    while True:
        try:
            run_id, auto_stop_reason = await asyncio.wait_for(
                asyncio.to_thread(
                    recorder.flush_tick,
                ),
                timeout=_DB_THREAD_TIMEOUT_S,
            )
            if run_id is None:
                if _is_tick_error_message(recorder._persistence.last_write_error):
                    recorder._persistence.clear_last_write_error()
                await asyncio.sleep(interval)
                continue
            if auto_stop_reason is not None:
                if auto_stop_reason == "max_duration":
                    logger.info(
                        "Auto-stopping run %s at the %.0f s recording limit",
                        run_id,
                        recorder._lifecycle.max_duration_s,
                    )
                else:
                    logger.info(
                        "Auto-stopping run %s after %.1fs without new data",
                        run_id,
                        recorder._lifecycle.no_data_timeout_s,
                    )
                await asyncio.wait_for(
                    asyncio.to_thread(
                        recorder.stop_recording,
                        _only_if_run_id=run_id,
                        reason=auto_stop_reason,
                    ),
                    timeout=_DB_THREAD_TIMEOUT_S,
                )
            if _is_tick_error_message(recorder._persistence.last_write_error):
                recorder._persistence.clear_last_write_error()
        except TimeoutError:
            recorder._persistence.set_last_write_error(_DB_TIMEOUT_ERROR)
            logger.warning(
                "Metrics logger DB call exceeded %.1fs timeout; skipping tick.",
                _DB_THREAD_TIMEOUT_S,
            )
        await asyncio.sleep(interval)
