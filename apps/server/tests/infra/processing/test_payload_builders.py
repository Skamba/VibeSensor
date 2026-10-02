"""Exercise processing payload builders for intake stats and alignment."""

from __future__ import annotations

from typing import cast

from vibesensor.infra.processing.buffers import ClientBuffer
from vibesensor.infra.processing.models import ProcessorConfig
from vibesensor.infra.processing.payload import build_time_alignment_payload


def _config(fft_n: int = 256) -> ProcessorConfig:
    return ProcessorConfig(
        sample_rate_hz=200,
        waveform_seconds=2,
        waveform_display_hz=50,
        fft_n=fft_n,
        spectrum_min_hz=0.0,
        spectrum_max_hz=100.0,
        accel_scale_g_per_lsb=None,
    )


def test_build_time_alignment_payload_handles_overlap_and_exclusions() -> None:
    buf1 = cast(ClientBuffer, object())
    buf2 = cast(ClientBuffer, object())
    buffers = {"s1": buf1, "s2": buf2}

    def _analysis_time_range(buf: ClientBuffer) -> tuple[float, float, bool] | None:
        if buf is buf1:
            return (10.0, 12.0, True)
        if buf is buf2:
            return (11.0, 13.0, False)
        return None

    payload = build_time_alignment_payload(
        buffers,
        ["s1", "missing", "s2"],
        analysis_time_range_fn=_analysis_time_range,
    )

    assert payload["sensors_included"] == ["s1", "s2"]
    assert payload["sensors_excluded"] == ["missing"]
    assert payload["aligned"] is False
    assert payload["clock_synced"] is False
    assert payload["shared_window"] is not None
    assert payload["shared_window"]["duration_s"] == 1.0
    assert payload["overlap_ratio"] == 0.3333


def test_build_time_alignment_payload_single_sensor_is_trivially_aligned() -> None:
    buf = cast(ClientBuffer, object())

    payload = build_time_alignment_payload(
        {"s1": buf},
        ["s1"],
        analysis_time_range_fn=lambda _: (5.0, 7.0, True),
    )

    assert payload["aligned"] is True
    assert payload["clock_synced"] is True
    assert payload["shared_window"] is None
    assert payload["overlap_ratio"] == 1.0
