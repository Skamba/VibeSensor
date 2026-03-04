"""Unit tests for vibesensor.processing.buffers.ClientBuffer."""

from __future__ import annotations

import numpy as np


class TestClientBuffer:
    """Tests for the ClientBuffer dataclass."""

    def test_create_buffer(self) -> None:
        from vibesensor.processing.buffers import ClientBuffer

        data = np.zeros((3, 100), dtype=np.float32)
        buf = ClientBuffer(data=data, capacity=100)
        assert buf.capacity == 100
        assert buf.count == 0
        assert buf.write_idx == 0
        assert buf.sample_rate_hz == 0
        assert buf.ingest_generation == 0
        assert buf.compute_generation == -1

    def test_invalidate_caches(self) -> None:
        from vibesensor.processing.buffers import ClientBuffer

        data = np.zeros((3, 100), dtype=np.float32)
        buf = ClientBuffer(data=data, capacity=100)
        buf.cached_spectrum_payload = {"x": [1.0]}
        buf.cached_spectrum_payload_generation = 5
        buf.cached_selected_payload = {"client_id": "test"}
        buf.cached_selected_payload_key = (1, 2, 3)

        buf.invalidate_caches()

        assert buf.cached_spectrum_payload is None
        assert buf.cached_spectrum_payload_generation == -1
        assert buf.cached_selected_payload is None
        assert buf.cached_selected_payload_key is None

    def test_slots_defined(self) -> None:
        """Verify slots are used for memory efficiency."""
        from vibesensor.processing.buffers import ClientBuffer

        assert hasattr(ClientBuffer, "__slots__")
