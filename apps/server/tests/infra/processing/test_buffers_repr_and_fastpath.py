"""Focused ClientBuffer debug and cache-invalidation behavior."""

from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffers import ClientBuffer


def _make_buf(capacity: int = 64) -> ClientBuffer:
    data = np.zeros((3, capacity), dtype=np.float32)
    return ClientBuffer(data=data, capacity=capacity)


def test_repr_is_compact_and_omits_raw_sample_data() -> None:
    buf = _make_buf(capacity=512)
    buf.data[0, :] = 1.23

    rendered = repr(buf)

    assert "capacity=512" in rendered
    assert "dtype" not in rendered
    assert len(rendered) < 200


class TestInvalidateCachesFastPath:
    """When caches are already None, invalidate_caches must be a no-op."""

    def test_cache_invalidation_is_idempotent(self) -> None:
        buf = _make_buf()
        buf.cached_spectrum_payload = {"combined_spectrum_amp_g": [1.0]}

        buf.invalidate_caches()
        buf.invalidate_caches()

        assert buf.cached_spectrum_payload is None
