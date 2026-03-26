"""Exercise buffer-store overflow trimming and warning behavior."""

from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffer_capacity import OverflowResult
from vibesensor.infra.processing.buffer_store import SignalBufferStore
from vibesensor.infra.processing.models import ProcessorConfig


def _config(**overrides: object) -> ProcessorConfig:
    base = {
        "sample_rate_hz": 200,
        "waveform_seconds": 2,
        "waveform_display_hz": 50,
        "fft_n": 128,
        "spectrum_min_hz": 0.0,
        "spectrum_max_hz": 100.0,
        "accel_scale_g_per_lsb": None,
    }
    base.update(overrides)
    return ProcessorConfig(**base)


def test_apply_overflow_policy_keeps_full_chunk_when_it_fits(caplog) -> None:
    store = SignalBufferStore(_config())
    chunk = np.arange(12, dtype=np.float32).reshape(4, 3)

    trimmed, overflow = store._apply_overflow_policy_unlocked(
        "sensor-fit",
        chunk,
        capacity=4,
    )

    assert overflow == OverflowResult(keep_count=4, drop_count=0, start_offset=0)
    np.testing.assert_array_equal(trimmed, chunk)
    assert caplog.text == ""


def test_apply_overflow_policy_trims_oldest_samples_and_warns(caplog) -> None:
    store = SignalBufferStore(_config())
    chunk = np.arange(18, dtype=np.float32).reshape(6, 3)

    with caplog.at_level("WARNING", logger="vibesensor.infra.processing.buffer_store"):
        trimmed, overflow = store._apply_overflow_policy_unlocked(
            "sensor-overflow",
            chunk,
            capacity=4,
        )

    assert overflow == OverflowResult(keep_count=4, drop_count=2, start_offset=2)
    np.testing.assert_array_equal(trimmed, chunk[-4:])
    assert "exceeds buffer capacity 4" in caplog.text
    assert "discarding 2 oldest samples" in caplog.text
