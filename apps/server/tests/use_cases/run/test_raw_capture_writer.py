from __future__ import annotations

import asyncio
import logging
import threading

import numpy as np
import pytest

from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector
from vibesensor.shared.types.raw_capture import RawCaptureLossStats, RawCaptureSensorClockSync
from vibesensor.use_cases.run.raw_capture_writer import RunRawCaptureWriter


def _samples() -> np.ndarray:
    return np.asarray([[1, 2, 3], [4, 5, 6]], dtype=np.int16)


def test_raw_capture_writer_persists_queue_invalid_and_write_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vibesensor.use_cases.run.raw_capture_writer._QUEUE_MAXSIZE", 1)

    class FakeHistoryDb:
        def __init__(self) -> None:
            self.first_started = threading.Event()
            self.allow_first_write = threading.Event()
            self.finalized_sensor_losses = None

        async def aappend_raw_capture_chunk(self, _run_id: str, chunk) -> None:
            if not self.first_started.is_set():
                self.first_started.set()
                await asyncio.to_thread(self.allow_first_write.wait)
            if chunk.client_id == "sensor-b":
                raise OSError("simulated raw capture write failure")

        async def afinalize_raw_capture(
            self,
            _run_id: str,
            *,
            run_start_monotonic_us: int | None = None,
            sensor_clock_sync=None,
            sensor_losses=None,
        ):
            assert run_start_monotonic_us == 1234
            assert sensor_clock_sync == {
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
            self.finalized_sensor_losses = sensor_losses
            return None

    history_db = FakeHistoryDb()
    ingest_diagnostics = IngestDiagnosticsCollector()
    writer = RunRawCaptureWriter(
        history_db=history_db,
        logger=logging.getLogger(__name__),
        ingest_diagnostics=ingest_diagnostics,
        sensor_sync_snapshotter=lambda client_ids: {
            client_id: RawCaptureSensorClockSync(
                clock_domain="server_monotonic" if client_id == "sensor-a" else "unverified",
                proof_state="verified" if client_id == "sensor-a" else "missing_sync",
            )
            for client_id in client_ids
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
        client_id="sensor-a",
        sample_rate_hz=800,
        t0_us=1200,
        samples=_samples(),
    )
    writer.capture_raw_samples(
        client_id="sensor-c",
        sample_rate_hz=0,
        t0_us=1300,
        samples=_samples(),
    )
    writer.note_late_packet_loss(client_id="sensor-b")

    history_db.allow_first_write.set()
    result = writer.finalize_run(
        "run-losses",
        sensor_losses={"sensor-d": RawCaptureLossStats(udp_ingest_queue_drop_count=2)},
    )
    assert result.completed is True
    assert result.manifest is None

    assert history_db.finalized_sensor_losses is not None
    assert history_db.finalized_sensor_losses["sensor-a"].queue_overflow_chunk_count == 1
    assert history_db.finalized_sensor_losses["sensor-b"].write_error_chunk_count == 1
    assert history_db.finalized_sensor_losses["sensor-b"].late_packet_chunk_count == 1
    assert history_db.finalized_sensor_losses["sensor-c"].invalid_chunk_count == 1
    assert history_db.finalized_sensor_losses["sensor-d"].udp_ingest_queue_drop_count == 2
    snapshot = ingest_diagnostics.raw_capture_snapshot()
    assert snapshot.queue_max_depth >= 1
    assert snapshot.dropped_chunks == 1
    assert snapshot.write_error_chunks == 1

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


def test_raw_capture_writer_finalize_returns_enqueue_timeout_when_control_offer_stays_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vibesensor.use_cases.run.raw_capture_writer._QUEUE_MAXSIZE", 1)
    monkeypatch.setattr(
        "vibesensor.use_cases.run.raw_capture_writer._CONTROL_REQUEST_ENQUEUE_TIMEOUT_S",
        0.05,
    )

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
    writer.capture_raw_samples(
        client_id="sensor-b",
        sample_rate_hz=800,
        t0_us=1100,
        samples=_samples(),
    )

    result = writer.finalize_run("run-enqueue-timeout")

    assert result.status == "enqueue_timeout"
    assert result.manifest is None
    assert result.queue_depth == 1
    assert result.error is not None
    history_db.block_append.set()
    assert writer.shutdown(timeout_s=1.0) is True


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


def test_raw_capture_writer_shutdown_returns_false_when_queue_offer_stays_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vibesensor.use_cases.run.raw_capture_writer._QUEUE_MAXSIZE", 1)

    class SlowHistoryDb:
        def __init__(self) -> None:
            self.block_append = threading.Event()

        async def aappend_raw_capture_chunk(self, _run_id: str, _chunk) -> None:
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
    writer.capture_raw_samples(
        client_id="sensor-b",
        sample_rate_hz=800,
        t0_us=1100,
        samples=_samples(),
    )

    assert writer.shutdown(timeout_s=0.1) is False

    history_db.block_append.set()
    thread = writer._thread
    assert thread is not None
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    writer._thread = None
