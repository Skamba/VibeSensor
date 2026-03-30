from __future__ import annotations

from vibesensor.infra.processing.buffer_registry import ClientBufferRegistry
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


def test_evicting_client_detaches_old_buffer_and_recreates_with_new_epoch() -> None:
    registry = ClientBufferRegistry(_config())
    with registry.lock:
        first = registry._get_or_create_unlocked("sensor-epoch")
    first_epoch = first.buffer_epoch

    registry.evict_clients(set())

    with registry.lock:
        recreated = registry._get_or_create_unlocked("sensor-epoch")

    assert recreated.buffer_epoch != first_epoch
    assert recreated is not first
