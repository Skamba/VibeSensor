"""Cover debug-query defaults and raw-sample projection behavior."""

from __future__ import annotations

import numpy as np

from vibesensor.infra.processing.buffer_store import SignalBufferStore
from vibesensor.infra.processing.debug_queries import DebugQueryReader
from vibesensor.infra.processing.models import DebugSpectrumRequest, ProcessorConfig


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


def test_debug_request_returns_empty_request_for_missing_client() -> None:
    store = SignalBufferStore(_config(fft_n=256, sample_rate_hz=400))
    queries = DebugQueryReader(store)

    request = queries.debug_request("missing")

    assert request == DebugSpectrumRequest(
        client_id="missing",
        sample_rate_hz=400,
        count=0,
        fft_block=None,
    )


def test_debug_request_uses_client_sample_rate_and_fft_block() -> None:
    store = SignalBufferStore(_config(fft_n=8, sample_rate_hz=200))
    queries = DebugQueryReader(store)
    client_id = "sensor-1"
    samples = np.arange(48, dtype=np.float32).reshape(16, 3)
    store.ingest(client_id, samples, sample_rate_hz=400)

    request = queries.debug_request(client_id)

    assert request.client_id == client_id
    assert request.sample_rate_hz == 400
    assert request.count == 16
    assert request.fft_block is not None
    np.testing.assert_array_equal(request.fft_block.T, samples[-8:])


def test_raw_samples_returns_error_for_missing_data() -> None:
    store = SignalBufferStore(_config())
    queries = DebugQueryReader(store)

    result = queries.raw_samples("missing", n_samples=32)

    assert result == {"error": "no data", "count": 0}


def test_raw_samples_caps_requested_count_to_available_samples() -> None:
    store = SignalBufferStore(_config(sample_rate_hz=800))
    queries = DebugQueryReader(store)
    client_id = "sensor-2"
    samples = np.arange(30, dtype=np.float32).reshape(10, 3)
    store.ingest(client_id, samples, sample_rate_hz=800)

    result = queries.raw_samples(client_id, n_samples=999)

    assert result["client_id"] == client_id
    assert result["sample_rate_hz"] == 800
    assert result["n_samples"] == 10
    assert result["x"] == [float(value) for value in samples[:, 0]]
    assert result["y"] == [float(value) for value in samples[:, 1]]
    assert result["z"] == [float(value) for value in samples[:, 2]]
