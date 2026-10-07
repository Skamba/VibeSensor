from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

import numpy as np
from test_support.clock_sync import complete_clock_sync

from vibesensor.ingest.protocol_messages import HelloMessage
from vibesensor.ingest.protocol_packing import pack_data
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.udp_data_rx import DataDatagramProtocol
from vibesensor.recording.raw_capture import (
    RawCaptureChunk,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
)
from vibesensor.recording.raw_capture_writer import RunRawCaptureWriter

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


class _FirstAppendBlocksHistoryDb:
    """Park the writer worker on its first append until ``block_append`` is set."""

    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.block_append = threading.Event()

    def append_raw_capture_chunk(self, _run_id: str, _chunk: RawCaptureChunk) -> None:
        if self.first_started.is_set():
            return
        self.first_started.set()
        self.block_append.wait()

    def checkpoint_raw_capture(self, _run_id: str, **_anchors: object) -> None:
        return None

    def finalize_raw_capture(
        self,
        _run_id: str,
        *,
        run_start_monotonic_us: int | None = None,
        sensor_clock_sync=None,
        sensor_losses=None,
    ) -> None:
        del run_start_monotonic_us, sensor_clock_sync, sensor_losses


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

        def append_raw_capture_chunk(self, _run_id: str, chunk: RawCaptureChunk) -> None:
            if not self.first_started.is_set():
                self.first_started.set()
                self.allow_first_write.wait()
            if chunk.client_id == "sensor-b":
                raise OSError("simulated raw capture write failure")
            self.stored_chunks.setdefault(chunk.client_id, []).append(chunk)
            self.first_write_completed.set()

        def checkpoint_raw_capture(self, _run_id: str, **_anchors: object) -> None:
            return None

        def finalize_raw_capture(
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
    # Live counts only the samples stored, so it ends at History's raw-sample
    # total: the failed write and the invalid chunk are not in either. It
    # describes the stopped run until the next one starts.
    assert writer.written_sample_count == manifest.total_samples
    writer.start_run("run-next")
    assert writer.written_sample_count == 0

    assert writer.shutdown()


class _StoringHistoryDb:
    def __init__(self) -> None:
        self.stored_chunks: dict[str, list[RawCaptureChunk]] = {}

    def append_raw_capture_chunk(self, _run_id: str, chunk: RawCaptureChunk) -> None:
        self.stored_chunks.setdefault(chunk.client_id, []).append(chunk)

    def checkpoint_raw_capture(self, _run_id: str, **_anchors: object) -> None:
        return None

    def finalize_raw_capture(
        self,
        run_id: str,
        *,
        run_start_monotonic_us: int | None = None,
        sensor_clock_sync=None,
        sensor_losses=None,
    ) -> RawCaptureManifest:
        return _manifest_from_chunks(
            run_id=run_id,
            stored_chunks=self.stored_chunks,
            run_start_monotonic_us=run_start_monotonic_us,
            sensor_clock_sync=dict(sensor_clock_sync or {}),
            sensor_losses=dict(sensor_losses or {}),
        )


def test_a_run_keeps_the_chunks_a_sensor_streams_before_its_hello() -> None:
    """After a server restart a sensor keeps streaming and says HELLO, which carries
    its sample rate, only every 2 s. Its DATA syncs its clock before that HELLO
    (#4146); the chunks stamped in between are written once the rate is known,
    not dropped as invalid (Pi, 2026.10.4.41: 9 of 356 chunks, a degraded run)."""
    client_id = "aabbccddee41"
    frame_samples = 200
    history_db = _StoringHistoryDb()
    writer = RunRawCaptureWriter(history_db=history_db, logger=logging.getLogger(__name__))
    writer.start_run("run-restart")
    registry = ClientRegistry()
    data_rx = DataDatagramProtocol(
        registry=registry, processor=MagicMock(), raw_capture_sink=writer
    )
    addr = ("10.4.0.2", 50123)
    offset_us = 90_000_000
    seq = 0

    def stream(count: int, *, synced: bool = True) -> None:
        nonlocal seq
        for _ in range(count):
            seq += 1
            t0_us = seq * 250_000 + (offset_us if synced else 0)
            samples = np.full((frame_samples, 3), seq, dtype=np.int16)
            data_rx._process_datagram(
                pack_data(bytes.fromhex(client_id), seq, t0_us, samples), addr
            )

    stream(1, synced=False)
    complete_clock_sync(registry, client_id, offset_us=offset_us)
    stream(7)
    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(client_id),
            control_port=9075,
            sample_rate_hz=800,
            frame_samples=frame_samples,
            name="node",
            firmware_version="fw",
        ),
        (addr[0], 9075),
    )
    stream(5)
    result = writer.finalize_run("run-restart")

    assert result.manifest is not None
    assert result.manifest.sensor_loss(client_id) is None
    chunks = history_db.stored_chunks[client_id]
    assert [chunk.t0_us for chunk in chunks] == [
        frame * 250_000 + offset_us for frame in range(2, 14)
    ]
    assert {chunk.sample_rate_hz for chunk in chunks} == {800}
    assert writer.shutdown()


def test_chunks_of_a_sensor_that_never_announces_its_rate_count_as_invalid() -> None:
    history_db = _StoringHistoryDb()
    writer = RunRawCaptureWriter(history_db=history_db, logger=logging.getLogger(__name__))
    writer.start_run("run-unannounced")

    for index in range(25):
        writer.capture_raw_samples(
            client_id="sensor-x", sample_rate_hz=None, t0_us=index, samples=_samples()
        )
    result = writer.finalize_run("run-unannounced")

    assert result.manifest is not None
    loss = result.manifest.sensor_loss("sensor-x")
    assert loss is not None
    assert loss.losses.invalid_chunk_count == 25
    assert history_db.stored_chunks == {}
    assert writer.shutdown()


def test_raw_capture_writer_finalize_timeout_returns_degraded_result() -> None:
    class HangingHistoryDb:
        def __init__(self) -> None:
            self.block_finalize = threading.Event()

        def append_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
            return None

        def checkpoint_raw_capture(self, _run_id: str, **_anchors: object) -> None:
            return None

        def finalize_raw_capture(
            self,
            _run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            del run_start_monotonic_us, sensor_clock_sync, sensor_losses
            self.block_finalize.wait()

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


def test_raw_capture_writer_notifies_late_finalize_after_timeout() -> None:
    class HangingHistoryDb:
        def __init__(self) -> None:
            self.block_finalize = threading.Event()

        def append_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
            return None

        def checkpoint_raw_capture(self, _run_id: str, **_anchors: object) -> None:
            return None

        def finalize_raw_capture(
            self,
            _run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            del run_start_monotonic_us, sensor_clock_sync, sensor_losses
            self.block_finalize.wait()
            return None

    history_db = HangingHistoryDb()
    completed = threading.Event()
    late_results: list[tuple[str, str]] = []
    writer = RunRawCaptureWriter(
        history_db=history_db,
        logger=logging.getLogger(__name__),
        late_finalize_callback=lambda run_id, result: (
            late_results.append((run_id, result.status)),
            completed.set(),
        ),
    )
    writer.start_run("run-timeout-late")

    result = writer.finalize_run("run-timeout-late", timeout_s=0.1)
    history_db.block_finalize.set()

    assert result.status == "timeout"
    assert completed.wait(timeout=2.0)
    assert late_results == [("run-timeout-late", "completed")]
    assert writer.shutdown(timeout_s=1.0) is True


def test_raw_capture_writer_finalize_returns_enqueue_timeout_when_queue_stays_full() -> None:
    history_db = _FirstAppendBlocksHistoryDb()
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
        def append_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
            return None

        def checkpoint_raw_capture(self, _run_id: str, **_anchors: object) -> None:
            return None

        def finalize_raw_capture(
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
    history_db = _FirstAppendBlocksHistoryDb()
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
