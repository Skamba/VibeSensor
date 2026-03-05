"""Metrics cache, settings rollback, and counter-delta regressions."""

from __future__ import annotations

import numpy as np

from vibesensor.processing import ClientBuffer


class TestClientBufferInvalidateCaches:
    """Verify the extracted invalidate_caches method works correctly."""

    def test_clears_all_cache_fields(self) -> None:
        buf = ClientBuffer(
            data=np.zeros((3, 100), dtype=np.float32),
            capacity=100,
        )
        # Simulate cached state
        buf.cached_spectrum_payload = {"freq": [1, 2]}
        buf.cached_spectrum_payload_generation = 5
        buf.cached_selected_payload = {"data": True}
        buf.cached_selected_payload_key = (1, 2, 3)

        buf.invalidate_caches()

        assert buf.cached_spectrum_payload is None
        assert buf.cached_spectrum_payload_generation == -1
        assert buf.cached_selected_payload is None
        assert buf.cached_selected_payload_key is None
