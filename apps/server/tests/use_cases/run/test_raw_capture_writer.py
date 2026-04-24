from __future__ import annotations

import asyncio
import logging
import threading

import numpy as np
import pytest

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
            sensor_losses=None,
        ):
            assert run_start_monotonic_us == 1234
            self.finalized_sensor_losses = sensor_losses
            return None

    history_db = FakeHistoryDb()
    writer = RunRawCaptureWriter(history_db=history_db, logger=logging.getLogger(__name__))
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

    history_db.allow_first_write.set()
    writer.finalize_run("run-losses")

    assert history_db.finalized_sensor_losses is not None
    assert history_db.finalized_sensor_losses["sensor-a"].queue_overflow_chunk_count == 1
    assert history_db.finalized_sensor_losses["sensor-b"].write_error_chunk_count == 1
    assert history_db.finalized_sensor_losses["sensor-c"].invalid_chunk_count == 1

    assert writer.shutdown()
