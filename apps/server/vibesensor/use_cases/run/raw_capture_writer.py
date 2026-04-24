"""Recorder-owned raw waveform sideband capture writer."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureManifest,
)

__all__ = ["RunRawCaptureWriter"]

_QUEUE_MAXSIZE = 2048


def _sync_call(db: Any, coro: Any) -> object:
    runner = getattr(db, "_run_on_engine_loop", None)
    if callable(runner):
        return runner(coro)
    import asyncio

    return asyncio.run(coro)


@dataclass(slots=True)
class _FinalizeRequest:
    run_id: str
    run_start_monotonic_us: int | None = None
    sensor_losses: _RunCaptureStats | None = None
    done: threading.Event = field(default_factory=threading.Event)
    manifest: RawCaptureManifest | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class _ShutdownRequest:
    done: threading.Event = field(default_factory=threading.Event)


@dataclass(slots=True)
class _MutableLossStats:
    queue_overflow_chunk_count: int = 0
    invalid_chunk_count: int = 0
    write_error_chunk_count: int = 0

    def freeze(self) -> RawCaptureLossStats:
        return RawCaptureLossStats(
            queue_overflow_chunk_count=self.queue_overflow_chunk_count,
            invalid_chunk_count=self.invalid_chunk_count,
            write_error_chunk_count=self.write_error_chunk_count,
        )


@dataclass(slots=True)
class _RunCaptureStats:
    by_client: dict[str, _MutableLossStats] = field(default_factory=dict)

    def _sensor(self, client_id: str) -> _MutableLossStats:
        return self.by_client.setdefault(client_id, _MutableLossStats())

    def record_queue_overflow(self, client_id: str) -> None:
        self._sensor(client_id).queue_overflow_chunk_count += 1

    def record_invalid_chunk(self, client_id: str) -> None:
        self._sensor(client_id).invalid_chunk_count += 1

    def record_write_error(self, client_id: str) -> None:
        self._sensor(client_id).write_error_chunk_count += 1

    def freeze(self) -> dict[str, RawCaptureLossStats]:
        frozen: dict[str, RawCaptureLossStats] = {}
        for client_id, stats in self.by_client.items():
            loss_stats = stats.freeze()
            if loss_stats.total_dropped_chunk_count <= 0:
                continue
            frozen[client_id] = loss_stats
        return frozen


class RunRawCaptureWriter:
    """Capture raw UDP chunks for the active run without blocking ingress."""

    __slots__ = (
        "_active_run_id",
        "_history_db",
        "_lock",
        "_logger",
        "_queue",
        "_run_stats",
        "_thread",
        "_run_start_monotonic_us",
    )

    def __init__(
        self,
        *,
        history_db: RunPersistence | None,
        logger: logging.Logger,
    ) -> None:
        self._history_db = (
            history_db
            if history_db is not None
            and callable(getattr(history_db, "aappend_raw_capture_chunk", None))
            and callable(getattr(history_db, "afinalize_raw_capture", None))
            else None
        )
        self._logger = logger
        self._lock = threading.RLock()
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
        except queue.Full:
            if run_stats is not None:
                run_stats.record_queue_overflow(client_id)
            self._logger.error(
                "Raw capture queue full for run %s; dropping raw chunk for %s",
                run_id,
                client_id,
            )

    def finalize_run(self, run_id: str) -> RawCaptureManifest | None:
        if self._history_db is None or self._thread is None:
            return None
        with self._lock:
            if self._active_run_id == run_id:
                self._active_run_id = None
            run_start_monotonic_us = self._run_start_monotonic_us
            self._run_start_monotonic_us = None
            run_stats = self._run_stats
            self._run_stats = None
        request = _FinalizeRequest(
            run_id=run_id,
            run_start_monotonic_us=run_start_monotonic_us,
            sensor_losses=run_stats,
        )
        self._queue.put(request)
        request.done.wait()
        if request.error is not None:
            raise RuntimeError(f"raw capture finalize failed for {run_id}") from request.error
        return request.manifest

    def shutdown(self, timeout_s: float = 5.0) -> bool:
        thread = self._thread
        if thread is None:
            return True
        request = _ShutdownRequest()
        self._queue.put(request)
        finished = request.done.wait(timeout=max(0.1, timeout_s))
        thread.join(timeout=max(0.1, timeout_s))
        self._thread = None
        return finished and not thread.is_alive()

    def _worker_loop(self) -> None:
        history_db = self._history_db
        assert history_db is not None
        while True:
            item = self._queue.get()
            try:
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
                                    sensor_losses=(
                                        item.sensor_losses.freeze()
                                        if item.sensor_losses is not None
                                        else None
                                    ),
                                ),
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
                    continue
                run_id, chunk, run_stats = item
                try:
                    _sync_call(history_db, history_db.aappend_raw_capture_chunk(run_id, chunk))
                except BaseException:  # noqa: BLE001
                    if run_stats is not None:
                        run_stats.record_write_error(chunk.client_id)
                    self._logger.error(
                        "Failed to persist raw capture chunk for run %s sensor %s",
                        run_id,
                        chunk.client_id,
                        exc_info=True,
                    )
            finally:
                self._queue.task_done()
