"""Recorder-owned raw waveform sideband capture writer."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np

from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
)
from vibesensor.shared.types.run_schema import RawCaptureFinalizeStatus

__all__ = ["RawCaptureFinalizeResult", "RunRawCaptureWriter"]

_QUEUE_MAXSIZE = 2048
_FINALIZE_WAIT_TIMEOUT_S = 5.0
_CONTROL_REQUEST_ENQUEUE_TIMEOUT_S = 1.0
_RAW_CAPTURE_APPEND_DB_TIMEOUT_S = 5.0
_RAW_CAPTURE_FINALIZE_DB_TIMEOUT_S = 10.0


@dataclass(frozen=True, slots=True)
class RawCaptureFinalizeResult:
    status: RawCaptureFinalizeStatus
    manifest: RawCaptureManifest | None = None
    error: str | None = None
    queue_depth: int | None = None

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def _sync_call(
    db: Any,
    coro: Any,
    *,
    timeout_s: float | None = None,
    operation: str = "raw_capture",
) -> object:
    runner = getattr(db, "_run_on_engine_loop", None)
    if callable(runner):
        if timeout_s is not None:
            return runner(
                coro,
                timeout_s=timeout_s,
                operation=operation,
            )
        return runner(coro)
    import asyncio

    return asyncio.run(coro)


@dataclass(slots=True)
class _FinalizeRequest:
    run_id: str
    run_start_monotonic_us: int | None = None
    sensor_clock_sync: Mapping[str, RawCaptureSensorClockSync] | None = None
    sensor_losses: _RunCaptureStats | None = None
    extra_sensor_losses: Mapping[str, RawCaptureLossStats] | None = None
    done: threading.Event = field(default_factory=threading.Event)
    manifest: RawCaptureManifest | None = None
    error: BaseException | None = None
    timed_out: bool = False
    late_callback_sent: bool = False


@dataclass(slots=True)
class _ShutdownRequest:
    done: threading.Event = field(default_factory=threading.Event)


@dataclass(slots=True)
class _MutableLossStats:
    late_packet_chunk_count: int = 0
    queue_overflow_chunk_count: int = 0
    invalid_chunk_count: int = 0
    write_error_chunk_count: int = 0

    def freeze(self) -> RawCaptureLossStats:
        return RawCaptureLossStats(
            late_packet_chunk_count=self.late_packet_chunk_count,
            queue_overflow_chunk_count=self.queue_overflow_chunk_count,
            invalid_chunk_count=self.invalid_chunk_count,
            write_error_chunk_count=self.write_error_chunk_count,
        )


@dataclass(slots=True)
class _RunCaptureStats:
    by_client: dict[str, _MutableLossStats] = field(default_factory=dict)
    seen_client_ids: set[str] = field(default_factory=set)

    def _sensor(self, client_id: str) -> _MutableLossStats:
        return self.by_client.setdefault(client_id, _MutableLossStats())

    def record_queue_overflow(self, client_id: str) -> None:
        self.seen_client_ids.add(client_id)
        self._sensor(client_id).queue_overflow_chunk_count += 1

    def record_late_packet(self, client_id: str) -> None:
        self.seen_client_ids.add(client_id)
        self._sensor(client_id).late_packet_chunk_count += 1

    def record_invalid_chunk(self, client_id: str) -> None:
        self.seen_client_ids.add(client_id)
        self._sensor(client_id).invalid_chunk_count += 1

    def record_write_error(self, client_id: str) -> None:
        self.seen_client_ids.add(client_id)
        self._sensor(client_id).write_error_chunk_count += 1

    def record_seen(self, client_id: str) -> None:
        self.seen_client_ids.add(client_id)

    def freeze(self) -> dict[str, RawCaptureLossStats]:
        frozen: dict[str, RawCaptureLossStats] = {}
        for client_id, stats in self.by_client.items():
            loss_stats = stats.freeze()
            if loss_stats.total_loss_event_count <= 0:
                continue
            frozen[client_id] = loss_stats
        return frozen


class RunRawCaptureWriter:
    """Capture raw UDP chunks for the active run without blocking ingress."""

    __slots__ = (
        "_active_run_id",
        "_history_db",
        "_ingest_diagnostics",
        "_late_finalize_callback",
        "_lock",
        "_logger",
        "_queue",
        "_run_stats",
        "_sensor_sync_snapshotter",
        "_thread",
        "_run_start_monotonic_us",
    )

    def __init__(
        self,
        *,
        history_db: RunPersistence | None,
        logger: logging.Logger,
        ingest_diagnostics: IngestDiagnosticsCollector | None = None,
        sensor_sync_snapshotter: (
            Callable[[tuple[str, ...]], Mapping[str, RawCaptureSensorClockSync] | None] | None
        ) = None,
        late_finalize_callback: Callable[[str, RawCaptureFinalizeResult], None] | None = None,
    ) -> None:
        self._history_db = (
            history_db
            if history_db is not None
            and callable(getattr(history_db, "aappend_raw_capture_chunk", None))
            and callable(getattr(history_db, "afinalize_raw_capture", None))
            else None
        )
        self._logger = logger
        self._ingest_diagnostics = ingest_diagnostics
        self._late_finalize_callback = late_finalize_callback
        self._lock = threading.RLock()
        self._sensor_sync_snapshotter = sensor_sync_snapshotter
        self._queue: queue.Queue[
            tuple[str, RawCaptureChunk, _RunCaptureStats | None]
            | _FinalizeRequest
            | _ShutdownRequest
        ] = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._active_run_id: str | None = None
        self._run_start_monotonic_us: int | None = None
        self._run_stats: _RunCaptureStats | None = None
        self._thread: threading.Thread | None = None
        if self._history_db is not None:
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="raw-capture-writer",
                daemon=True,
            )
            self._thread.start()

    def start_run(self, run_id: str, *, run_start_monotonic_us: int | None = None) -> None:
        with self._lock:
            self._active_run_id = run_id
            self._run_start_monotonic_us = run_start_monotonic_us
            self._run_stats = _RunCaptureStats()

    def capture_raw_samples(
        self,
        *,
        client_id: str,
        sample_rate_hz: int | None,
        t0_us: int,
        samples: np.ndarray,
    ) -> None:
        history_db = self._history_db
        if history_db is None:
            return
        with self._lock:
            run_id = self._active_run_id
            run_stats = self._run_stats
        if run_id is None:
            return
        normalized_rate = int(sample_rate_hz or 0)
        if normalized_rate <= 0:
            if run_stats is not None:
                run_stats.record_invalid_chunk(client_id)
            return
        samples_i16 = np.ascontiguousarray(samples, dtype=np.int16)
        if samples_i16.ndim != 2 or samples_i16.shape[1] != 3 or samples_i16.shape[0] <= 0:
            if run_stats is not None:
                run_stats.record_invalid_chunk(client_id)
            return
        if run_stats is not None:
            run_stats.record_seen(client_id)
        try:
            self._queue.put_nowait(
                (
                    run_id,
                    RawCaptureChunk(
                        client_id=client_id,
                        sample_rate_hz=normalized_rate,
                        t0_us=int(t0_us),
                        sample_count=int(samples_i16.shape[0]),
                        samples_i16le=samples_i16.tobytes(order="C"),
                    ),
                    run_stats,
                )
            )
            if self._ingest_diagnostics is not None:
                self._ingest_diagnostics.note_raw_capture_queue_depth(self._queue.qsize())
        except queue.Full:
            if run_stats is not None:
                run_stats.record_queue_overflow(client_id)
            if self._ingest_diagnostics is not None:
                self._ingest_diagnostics.note_raw_capture_drop(depth=self._queue.qsize())
            self._logger.error(
                "Raw capture queue full for run %s; dropping raw chunk for %s",
                run_id,
                client_id,
            )

    def finalize_run(
        self,
        run_id: str,
        *,
        sensor_losses: Mapping[str, RawCaptureLossStats] | None = None,
        timeout_s: float = _FINALIZE_WAIT_TIMEOUT_S,
    ) -> RawCaptureFinalizeResult:
        if self._history_db is None or self._thread is None:
            return RawCaptureFinalizeResult(status="not_configured")
        with self._lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
            run_start_monotonic_us = self._run_start_monotonic_us
            self._run_start_monotonic_us = None
            run_stats = self._run_stats
            self._run_stats = None
        sensor_clock_sync = None
        if (
            self._sensor_sync_snapshotter is not None
            and run_stats is not None
            and run_stats.seen_client_ids
        ):
            sensor_clock_sync = self._sensor_sync_snapshotter(
                tuple(sorted(run_stats.seen_client_ids)),
            )
        request = _FinalizeRequest(
            run_id=run_id,
            run_start_monotonic_us=run_start_monotonic_us,
            sensor_clock_sync=sensor_clock_sync,
            sensor_losses=run_stats,
            extra_sensor_losses=sensor_losses,
        )
        try:
            self._queue.put(
                request,
                timeout=_bounded_wait_timeout(_CONTROL_REQUEST_ENQUEUE_TIMEOUT_S),
            )
        except queue.Full:
            queue_depth = self._queue.qsize()
            self._logger.error(
                "Timed out queueing raw capture finalize for run %s; queue depth=%s",
                run_id,
                queue_depth,
            )
            return RawCaptureFinalizeResult(
                status="enqueue_timeout",
                error=f"raw capture finalize enqueue timed out for {run_id}",
                queue_depth=queue_depth,
            )
        if self._ingest_diagnostics is not None:
            self._ingest_diagnostics.note_raw_capture_queue_depth(self._queue.qsize())
        finished = request.done.wait(timeout=_bounded_wait_timeout(timeout_s))
        if not finished:
            queue_depth = self._queue.qsize()
            request.timed_out = True
            if request.done.is_set():
                self._notify_late_finalize(request)
            self._logger.error(
                "Timed out waiting %.2fs for raw capture finalize for run %s; queue depth=%s",
                max(0.0, float(timeout_s)),
                run_id,
                queue_depth,
            )
            return RawCaptureFinalizeResult(
                status="timeout",
                error=f"raw capture finalize timed out for {run_id}",
                queue_depth=queue_depth,
            )
        if request.error is not None:
            return RawCaptureFinalizeResult(
                status="failed",
                error=f"raw capture finalize failed for {run_id}: {request.error}",
                queue_depth=self._queue.qsize(),
            )
        return RawCaptureFinalizeResult(
            status="completed",
            manifest=request.manifest,
            queue_depth=self._queue.qsize(),
        )

    def note_late_packet_loss(self, *, client_id: str) -> None:
        with self._lock:
            run_stats = self._run_stats
            run_id = self._active_run_id
        if run_id is None or run_stats is None:
            return
        run_stats.record_late_packet(client_id)

    def shutdown(self, timeout_s: float = 5.0) -> bool:
        thread = self._thread
        if thread is None:
            return True
        request = _ShutdownRequest()
        try:
            self._queue.put(
                request,
                timeout=_bounded_wait_timeout(min(timeout_s, _CONTROL_REQUEST_ENQUEUE_TIMEOUT_S)),
            )
        except queue.Full:
            self._logger.error(
                "Timed out queueing raw capture shutdown; queue depth=%s",
                self._queue.qsize(),
            )
            return False
        if self._ingest_diagnostics is not None:
            self._ingest_diagnostics.note_raw_capture_queue_depth(self._queue.qsize())
        finished = request.done.wait(timeout=_bounded_wait_timeout(timeout_s))
        thread.join(timeout=_bounded_wait_timeout(timeout_s))
        if not thread.is_alive():
            self._thread = None
            return finished
        self._logger.error(
            "Raw capture worker did not exit within %.2fs during shutdown",
            max(0.0, float(timeout_s)),
        )
        return False

    def _worker_loop(self) -> None:
        history_db = self._history_db
        assert history_db is not None
        while True:
            item = self._queue.get()
            try:
                if self._ingest_diagnostics is not None:
                    self._ingest_diagnostics.note_raw_capture_queue_depth(self._queue.qsize())
                if isinstance(item, _ShutdownRequest):
                    item.done.set()
                    return
                if isinstance(item, _FinalizeRequest):
                    try:
                        item.manifest = cast(
                            RawCaptureManifest | None,
                            _sync_call(
                                history_db,
                                history_db.afinalize_raw_capture(
                                    item.run_id,
                                    run_start_monotonic_us=item.run_start_monotonic_us,
                                    sensor_clock_sync=item.sensor_clock_sync,
                                    sensor_losses=_merge_sensor_losses(
                                        item.sensor_losses.freeze()
                                        if item.sensor_losses is not None
                                        else None,
                                        item.extra_sensor_losses,
                                    ),
                                ),
                                timeout_s=_RAW_CAPTURE_FINALIZE_DB_TIMEOUT_S,
                                operation="raw_capture_finalize",
                            ),
                        )
                    except BaseException as exc:  # noqa: BLE001
                        item.error = exc
                        self._logger.error(
                            "Failed to finalize raw capture for run %s",
                            item.run_id,
                            exc_info=True,
                        )
                    finally:
                        item.done.set()
                        if item.timed_out:
                            self._notify_late_finalize(item)
                    continue
                run_id, chunk, run_stats = item
                try:
                    _sync_call(
                        history_db,
                        history_db.aappend_raw_capture_chunk(run_id, chunk),
                        timeout_s=_RAW_CAPTURE_APPEND_DB_TIMEOUT_S,
                        operation="raw_capture_append",
                    )
                except BaseException:  # noqa: BLE001
                    if run_stats is not None:
                        run_stats.record_write_error(chunk.client_id)
                    if self._ingest_diagnostics is not None:
                        self._ingest_diagnostics.note_raw_capture_write_error()
                    self._logger.error(
                        "Failed to persist raw capture chunk for run %s sensor %s",
                        run_id,
                        chunk.client_id,
                        exc_info=True,
                    )
            finally:
                self._queue.task_done()

    def _notify_late_finalize(self, request: _FinalizeRequest) -> None:
        callback = self._late_finalize_callback
        if callback is None:
            return
        if request.late_callback_sent:
            return
        request.late_callback_sent = True
        if request.error is not None:
            result = RawCaptureFinalizeResult(
                status="failed",
                error=f"raw capture finalize failed for {request.run_id}: {request.error}",
                queue_depth=self._queue.qsize(),
            )
        else:
            result = RawCaptureFinalizeResult(
                status="completed",
                manifest=request.manifest,
                queue_depth=self._queue.qsize(),
            )
        try:
            callback(request.run_id, result)
        except BaseException:  # noqa: BLE001
            self._logger.exception(
                "Late raw capture finalize callback failed for run %s",
                request.run_id,
            )


def _merge_sensor_losses(
    primary: Mapping[str, RawCaptureLossStats] | None,
    secondary: Mapping[str, RawCaptureLossStats] | None,
) -> dict[str, RawCaptureLossStats] | None:
    if not primary and not secondary:
        return None
    merged: dict[str, RawCaptureLossStats] = {}
    client_ids = set(primary or ()) | set(secondary or ())
    for client_id in sorted(client_ids):
        losses = RawCaptureLossStats()
        if primary is not None:
            losses = losses.merged(primary.get(client_id, RawCaptureLossStats()))
        if secondary is not None:
            losses = losses.merged(secondary.get(client_id, RawCaptureLossStats()))
        if losses.total_loss_event_count <= 0:
            continue
        merged[client_id] = losses
    return merged or None


def _bounded_wait_timeout(timeout_s: float) -> float:
    return max(0.1, float(timeout_s))
