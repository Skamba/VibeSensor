"""Unit tests for ClientBuffer.__repr__ and invalidate_caches fast-path.

The existing test_processing_buffers.py covers creation, normal cache
invalidation, and slot existence.  These tests fill the remaining gaps:

- __repr__: must be compact and must NOT dump raw numpy array data
- invalidate_caches fast-path: when both caches are already None, the
  method must return early without touching the generation counters
"""

from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffers import ClientBuffer


def _make_buf(capacity: int = 64) -> ClientBuffer:
    data = np.zeros((3, capacity), dtype=np.float32)
    return ClientBuffer(data=data, capacity=capacity)


class TestClientBufferRepr:
    """__repr__ should be compact and not embed the raw ndarray."""

    def test_repr_is_a_string(self) -> None:
        buf = _make_buf()
        assert isinstance(repr(buf), str)

    def test_repr_contains_capacity(self) -> None:
        buf = _make_buf(capacity=512)
        assert "512" in repr(buf)

    def test_repr_does_not_contain_array_data(self) -> None:
        """Embedding the numpy array would make repr unusably large."""
        buf = _make_buf(capacity=100)
        buf.data[0, :] = 1.23  # fill with non-zero so naive repr would show data
        r = repr(buf)
        # A raw ndarray repr contains the dtype keyword; our compact repr must not
        assert "dtype" not in r, "repr must not embed raw ndarray data"

    def test_repr_includes_generation_counters(self) -> None:
        buf = _make_buf()
        buf.ingest_generation = 7
        buf.compute_generation = 5
        r = repr(buf)
        assert "igen=7" in r
        assert "cgen=5" in r


class TestInvalidateCachesFastPath:
    """When caches are already None, invalidate_caches must be a no-op."""

    def test_no_op_when_caches_already_clear(self) -> None:
        """Called on a fresh buffer (caches are None) must not raise or mutate
        the generation fields.
        """
        buf = _make_buf()
        # Confirm caches are already None
        assert buf.cached_spectrum_payload is None

        before_gen = buf.cached_spectrum_payload_generation
        buf.invalidate_caches()
        # The fast-path return must NOT reset the generation counter to -1
        # again (it's already -1 — we just verify no side effects occurred
        # beyond what the initial state established).
        assert buf.cached_spectrum_payload_generation == before_gen

    def test_idempotent_double_call(self) -> None:
        """Calling invalidate_caches twice in a row must not raise."""
        buf = _make_buf()
        buf.cached_spectrum_payload = {"combined_spectrum_amp_g": [1.0]}
        buf.invalidate_caches()
        # Second call triggers the fast-path
        buf.invalidate_caches()
        assert buf.cached_spectrum_payload is None
