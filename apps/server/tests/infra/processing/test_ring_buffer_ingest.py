from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.ring_buffer_ingest import apply_ring_buffer_ingest


def _make_buffer(*, capacity: int = 4, fill: float = 0.0) -> ClientBuffer:
    return ClientBuffer(
        data=np.full((3, capacity), fill, dtype=np.float32),
        capacity=capacity,
    )


def test_apply_ring_buffer_ingest_writes_without_wraparound() -> None:
    buf = _make_buffer(capacity=5)
    chunk = np.array(
        [
            [1.0, 10.0, 100.0],
            [2.0, 20.0, 200.0],
            [3.0, 30.0, 300.0],
        ],
        dtype=np.float32,
    )

    written = apply_ring_buffer_ingest(buf, chunk, t0_us=1_000_000)

    assert written == 3
    assert buf.write_idx == 3
    assert buf.count == 3
    assert buf.last_t0_us == 1_000_000
    assert buf.samples_since_t0 == 3
    assert buf.ingest_generation == 1
    np.testing.assert_array_equal(buf.data[:, :3], chunk.T)


def test_apply_ring_buffer_ingest_wraps_and_saturates_count() -> None:
    buf = _make_buffer(capacity=4, fill=-1.0)
    buf.write_idx = 3
    buf.count = 4
    chunk = np.array(
        [
            [1.0, 10.0, 100.0],
            [2.0, 20.0, 200.0],
        ],
        dtype=np.float32,
    )

    written = apply_ring_buffer_ingest(buf, chunk)

    assert written == 2
    assert buf.write_idx == 1
    assert buf.count == 4
    assert buf.ingest_generation == 1
    expected = np.array(
        [
            [2.0, -1.0, -1.0, 1.0],
            [20.0, -1.0, -1.0, 10.0],
            [200.0, -1.0, -1.0, 100.0],
        ],
        dtype=np.float32,
    )
    np.testing.assert_array_equal(buf.data, expected)


def test_apply_ring_buffer_ingest_does_not_regress_last_t0_for_older_frame() -> None:
    buf = _make_buffer(capacity=8)

    apply_ring_buffer_ingest(
        buf,
        np.ones((4, 3), dtype=np.float32),
        t0_us=1_000_000,
    )
    apply_ring_buffer_ingest(
        buf,
        np.ones((2, 3), dtype=np.float32),
        t0_us=900_000,
    )

    assert buf.last_t0_us == 1_000_000
    assert buf.samples_since_t0 == 6
    assert buf.ingest_generation == 2


def test_apply_ring_buffer_ingest_clamps_samples_since_t0() -> None:
    buf = _make_buffer(capacity=4)
    buf.last_t0_us = 1_000_000
    buf.samples_since_t0 = (2**28) - 1

    apply_ring_buffer_ingest(buf, np.ones((2, 3), dtype=np.float32))

    assert buf.last_t0_us == 1_000_000
    assert buf.samples_since_t0 == 2**28
    assert buf.ingest_generation == 1
