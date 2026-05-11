from __future__ import annotations

from dataclasses import dataclass

from vibesensor.infra.processing.buffer_mutations import ClientBufferMutator
from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import FloatArray, ProcessorConfig
from vibesensor.infra.processing.snapshot_builder import compute_snapshot_window


@dataclass(frozen=True, slots=True)
class PreparedSnapshotWindows:
    """Copied sample windows ready for metrics snapshot construction."""

    time_window: FloatArray
    fft_block: FloatArray | None


def prepare_snapshot_windows(
    *,
    buf: ClientBuffer,
    config: ProcessorConfig,
    buffer_mutator: ClientBufferMutator,
    sample_rate_hz: int,
) -> PreparedSnapshotWindows:
    """Copy the latest time-domain and FFT windows from a locked client buffer."""
    window = compute_snapshot_window(
        count=buf.count,
        capacity=buf.capacity,
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=config.waveform_seconds,
        fft_n=config.fft_n,
    )

    fft_block: FloatArray | None = None
    if window.needs_separate_fft_block:
        fft_block = buffer_mutator.copy_latest(buf, config.fft_n)
        time_window = fft_block[:, -window.n_time :]
    else:
        time_window = buffer_mutator.copy_latest(buf, window.n_time)
        if buf.count >= config.fft_n:
            fft_block = time_window[:, -config.fft_n :]
    return PreparedSnapshotWindows(time_window=time_window, fft_block=fft_block)
