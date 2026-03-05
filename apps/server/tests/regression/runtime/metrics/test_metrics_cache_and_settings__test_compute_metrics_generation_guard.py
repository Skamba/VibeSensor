"""Metrics cache, settings rollback, and counter-delta regressions."""

from __future__ import annotations

import numpy as np

from vibesensor.processing import SignalProcessor


class TestComputeMetricsGenerationGuard:
    """Phase 3 should not overwrite fresher results with stale ones."""

    def test_stale_generation_does_not_overwrite(self) -> None:
        sp = SignalProcessor(
            sample_rate_hz=1000,
            waveform_seconds=2,
            waveform_display_hz=50,
            fft_n=256,
        )
        client = "test-client"
        # Ingest enough samples to compute
        chunk = np.random.default_rng(42).standard_normal((512, 3)).astype(np.float32) * 0.01
        sp.ingest(client, chunk, sample_rate_hz=1000)

        # First compute
        sp.compute_metrics(client)

        with sp._lock:
            buf = sp._buffers[client]
            gen_after_first = buf.compute_generation
            # Artificially advance the compute generation to simulate a fresher result
            buf.compute_generation = gen_after_first + 100

        # Compute again — this should NOT overwrite because snap_ingest_gen < compute_generation
        sp.compute_metrics(client)

        with sp._lock:
            buf = sp._buffers[client]
            # Should still be the artificially advanced generation
            assert buf.compute_generation == gen_after_first + 100
