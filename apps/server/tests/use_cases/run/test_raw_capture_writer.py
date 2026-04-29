from __future__ import annotations

import asyncio
import logging
import threading

import numpy as np

from vibesensor.shared.types.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
)
from vibesensor.use_cases.run.raw_capture_writer import RunRawCaptureWriter

_QUEUE_OVERFILL_CHUNK_COUNT = 2_100


def _samples() -> np.ndarray:
    return np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)


def _overfill_capture_queue(
    writer: RunRawCaptureWriter,
    *,
    client_id: str,
    start_t0_us: int,
    count: int = _QUEUE_OVERFILL_CHUNK_COUNT,
) -> None:
    for index in range(count):
        writer.capture_raw_samples(
            client_id=client_id,
            sample_rate_hz=800,
            t0_us=start_t0_us + index,
            samples=_samples(),
        )


def _merged_loss_stats(sensor_losses: dict[str, RawCaptureLossStats] | None) -> RawCaptureLossStats:
    merged = RawCaptureLossStats()
    for loss_stats in (sensor_losses or {}).values():
        merged = merged.merged(loss_stats)
    return merged


def _manifest_from_chunks(
    *,
    run_id: str,
    stored_chunks: dict[str, list[RawCaptureChunk]],
    run_start_monotonic_us: int | None,
    sensor_clock_sync: dict[str, RawCaptureSensorClockSync] | None,
    sensor_losses: dict[str, RawCaptureLossStats] | None,
) -> RawCaptureManifest:
    sensor_manifests: list[RawCaptureSensorManifest] = []
    total_samples = 0
    total_bytes = 0
    for client_id, chunks in sorted(stored_chunks.items()):
        sample_count = sum(chunk.sample_count for chunk in chunks)
        bytes_written = sum(len(chunk.samples_i16le) for chunk in chunks)
        total_samples += sample_count
        total_bytes += bytes_written
        sensor_manifests.append(
            RawCaptureSensorManifest(
                client_id=client_id,
                sample_rate_hz=chunks[0].sample_rate_hz,
                data_file=f"{client_id}.raw.i16le",
                index_file=f"{client_id}.index.jsonl",
                sample_count=sample_count,
                chunk_count=len(chunks),
                bytes_written=bytes_written,
                first_t0_us=chunks[0].t0_us,
                last_t0_us=chunks[-1].t0_us,
                clock_sync=(
                    sensor_clock_sync.get(client_id) if sensor_clock_sync is not None else None
                ),
                declared_sample_rate_hz=chunks[0].sample_rate_hz,
                sample_rate_proof_state="observed_consistent",
            )
        )
    return RawCaptureManifest(
        run_id=run_id,
        relative_dir=f"raw-runs/{run_id}",
        sensors=tuple(sensor_manifests),
        total_samples=total_samples,
        total_bytes=total_bytes,
        created_at="2025-01-01T00:00:00Z",
        run_start_monotonic_us=run_start_monotonic_us,
        sensor_losses=tuple(
            RawCaptureSensorLossStats(client_id=client_id, losses=loss_stats)
            for client_id, loss_stats in sorted((sensor_losses or {}).items())
            if loss_stats.total_loss_event_count > 0
        ),
        losses=_merged_loss_stats(sensor_losses),
    )


def test_raw_capture_writer_finalize_returns_manifest_with_persisted_loss_counts() -> None:
    expected_sync = {
        "sensor-a": RawCaptureSensorClockSync(
            clock_domain="server_monotonic",
            proof_state="verified",
        ),
        "sensor-b": RawCaptureSensorClockSync(
            clock_domain="unverified",
            proof_state="missing_sync",
        ),
        "sensor-c": RawCaptureSensorClockSync(
            clock_domain="unverified",
            proof_state="missing_sync",
        ),
    }

    class FakeHistoryDb:
        def __init__(self) -> None:
            self.first_started = threading.Event()
            self.allow_first_write = threading.Event()
            self.first_write_completed = threading.Event()
            self.stored_chunks: dict[str, list[RawCaptureChunk]] = {}

        async def aappend_raw_capture_chunk(self, _run_id: str, chunk: RawCaptureChunk) -> None:
            if not self.first_started.is_set():
                self.first_started.set()
                await asyncio.to_thread(self.allow_first_write.wait)
            if chunk.client_id == "sensor-b":
                raise OSError("simulated raw capture write failure")
            self.stored_chunks.setdefault(chunk.client_id, []).append(chunk)
            self.first_write_completed.set()

        async def afinalize_raw_capture(
            self,
            run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            return _manifest_from_chunks(
                run_id=run_id,
                stored_chunks=self.stored_chunks,
                run_start_monotonic_us=run_start_monotonic_us,
                sensor_clock_sync=dict(sensor_clock_sync or {}),
                sensor_losses=dict(sensor_losses or {}),
            )

    history_db = FakeHistoryDb()
    writer = RunRawCaptureWriter(
        history_db=history_db,
        logger=logging.getLogger(__name__),
        sensor_sync_snapshotter=lambda client_ids: {
            client_id: expected_sync[client_id] for client_id in client_ids
        },
    )
    writer.start_run("run-losses", run_start_monotonic_us=1234)

    writer.capture_raw_samples(
        client_id="sensor-a",
        sample_rate_hz=800,
        t0_us=1000,
        samples=_samples(),
    )
    assert history_db.first_started.wait(timeout=2.0)

    writer.capture_raw_samples(
        client_id="sensor-b",
        sample_rate_hz=800,
        t0_us=1100,
        samples=_samples(),
    )
    writer.capture_raw_samples(
        client_id="sensor-c",
        sample_rate_hz=0,
        t0_us=1200,
        samples=_samples(),
    )
    writer.note_late_packet_loss(client_id="sensor-b")
    _overfill_capture_queue(writer, client_id="sensor-a", start_t0_us=2000)

    history_db.allow_first_write.set()
    assert history_db.first_write_completed.wait(timeout=2.0)
    result = writer.finalize_run(
        "run-losses",
        sensor_losses={"sensor-d": RawCaptureLossStats(udp_ingest_queue_drop_count=2)},
    )

    assert result.completed is True
    manifest = result.manifest
    assert manifest is not None
    assert manifest.run_start_monotonic_us == 1234
    assert manifest.total_samples > 0
    assert manifest.total_bytes > 0
    sensor_a_manifest = manifest.sensor_manifest("sensor-a")
    assert sensor_a_manifest is not None
    assert sensor_a_manifest.clock_sync == expected_sync["sensor-a"]
    sensor_a_loss = manifest.sensor_loss("sensor-a")
    assert sensor_a_loss is not None
    assert sensor_a_loss.losses.queue_overflow_chunk_count > 0
    sensor_b_loss = manifest.sensor_loss("sensor-b")
    assert sensor_b_loss is not None
    assert sensor_b_loss.losses.write_error_chunk_count == 1
    assert sensor_b_loss.losses.late_packet_chunk_count == 1
    sensor_c_loss = manifest.sensor_loss("sensor-c")
    assert sensor_c_loss is not None
    assert sensor_c_loss.losses.invalid_chunk_count == 1
    sensor_d_loss = manifest.sensor_loss("sensor-d")
    assert sensor_d_loss is not None
    assert sensor_d_loss.losses.udp_ingest_queue_drop_count == 2

    assert writer.shutdown()


def test_raw_capture_writer_finalize_timeout_returns_degraded_result() -> None:
    class HangingHistoryDb:
        def __init__(self) -> None:
            self.block_finalize = threading.Event()

        async def aappend_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
            return None

        async def afinalize_raw_capture(
            self,
            _run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            del run_start_monotonic_us, sensor_clock_sync, sensor_losses
            await asyncio.to_thread(self.block_finalize.wait)

    history_db = HangingHistoryDb()
    writer = RunRawCaptureWriter(
        history_db=history_db,
        logger=logging.getLogger(__name__),
    )
    writer.start_run("run-timeout")

    result = writer.finalize_run("run-timeout", timeout_s=0.1)

    assert result.status == "timeout"
    assert result.manifest is None
    assert result.error is not None
    history_db.block_finalize.set()
    assert writer.shutdown(timeout_s=1.0) is True


def test_raw_capture_writer_finalize_returns_enqueue_timeout_when_queue_stays_full() -> None:
    class SlowHistoryDb:
        def __init__(self) -> None:
            self.first_started = threading.Event()
            self.block_append = threading.Event()

        async def aappend_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
            self.first_started.set()
            await asyncio.to_thread(self.block_append.wait)

        async def afinalize_raw_capture(
            self,
            _run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            del run_start_monotonic_us, sensor_clock_sync, sensor_losses
            return None

    history_db = SlowHistoryDb()
    writer = RunRawCaptureWriter(
        history_db=history_db,
        logger=logging.getLogger(__name__),
    )
    writer.start_run("run-enqueue-timeout")
    writer.capture_raw_samples(
        client_id="sensor-a",
        sample_rate_hz=800,
        t0_us=1000,
        samples=_samples(),
    )
    assert history_db.first_started.wait(timeout=2.0)
    _overfill_capture_queue(writer, client_id="sensor-b", start_t0_us=1100)

    result = writer.finalize_run("run-enqueue-timeout")

    assert result.status == "enqueue_timeout"
    assert result.manifest is None
    assert result.error is not None
    history_db.block_append.set()
    assert writer.shutdown(timeout_s=5.0) is True


def test_raw_capture_writer_finalize_failure_returns_failed_result() -> None:
    class FailingHistoryDb:
        async def aappend_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
            return None

        async def afinalize_raw_capture(
            self,
            _run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            del run_start_monotonic_us, sensor_clock_sync, sensor_losses
            raise OSError("simulated finalize failure")

    writer = RunRawCaptureWriter(
        history_db=FailingHistoryDb(),
        logger=logging.getLogger(__name__),
    )
    writer.start_run("run-failed")

    result = writer.finalize_run("run-failed")

    assert result.status == "failed"
    assert result.manifest is None
    assert result.error is not None
    assert "simulated finalize failure" in result.error
    assert writer.shutdown(timeout_s=1.0) is True


def test_raw_capture_writer_shutdown_returns_false_when_queue_stays_full() -> None:
    class SlowHistoryDb:
        def __init__(self) -> None:
            self.first_started = threading.Event()
            self.block_append = threading.Event()

        async def aappend_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
            self.first_started.set()
            await asyncio.to_thread(self.block_append.wait)

        async def afinalize_raw_capture(
            self,
            _run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            del run_start_monotonic_us, sensor_clock_sync, sensor_losses
            return None

    history_db = SlowHistoryDb()
    writer = RunRawCaptureWriter(
        history_db=history_db,
        logger=logging.getLogger(__name__),
    )
    writer.start_run("run-shutdown-full")
    writer.capture_raw_samples(
        client_id="sensor-a",
        sample_rate_hz=800,
        t0_us=1000,
        samples=_samples(),
    )
    assert history_db.first_started.wait(timeout=2.0)
    _overfill_capture_queue(writer, client_id="sensor-b", start_t0_us=1100)

    assert writer.shutdown(timeout_s=0.1) is False

    history_db.block_append.set()
    assert writer.shutdown(timeout_s=5.0) is True
