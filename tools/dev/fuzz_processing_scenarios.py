"""Hypothesis scenario strategies for processing fuzz targets."""

from __future__ import annotations

from typing import Any


def strength_case_strategy(st: Any) -> Any:
    @st.composite
    def _build(draw: Any) -> dict[str, object]:
        axis_count = draw(st.integers(min_value=0, max_value=3))
        lengths = draw(
            st.lists(
                st.integers(min_value=0, max_value=192),
                min_size=axis_count,
                max_size=axis_count,
            )
        )
        axis_spectra = [
            draw(
                st.lists(
                    st.floats(
                        min_value=-1.0,
                        max_value=4.0,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                    min_size=length,
                    max_size=length,
                )
            )
            for length in lengths
        ]
        axis_count_for_mean = draw(
            st.one_of(
                st.none(),
                st.integers(min_value=1, max_value=4),
            )
        )
        freq_step_hz = draw(
            st.floats(
                min_value=0.1, max_value=12.0, allow_nan=False, allow_infinity=False
            )
        )
        start_hz = draw(
            st.floats(
                min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False
            )
        )
        center_idx = draw(
            st.integers(min_value=0, max_value=max(0, min(lengths or [0]) - 1))
        )
        bandwidth_hz = draw(
            st.floats(
                min_value=0.05, max_value=8.0, allow_nan=False, allow_infinity=False
            )
        )
        epsilon_g = draw(
            st.one_of(
                st.none(),
                st.floats(
                    min_value=1e-12,
                    max_value=0.1,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            )
        )
        return {
            "axis_spectra": axis_spectra,
            "axis_count_for_mean": axis_count_for_mean,
            "freq_step_hz": freq_step_hz,
            "start_hz": start_hz,
            "center_idx": center_idx,
            "bandwidth_hz": bandwidth_hz,
            "epsilon_g": epsilon_g,
        }

    return _build()


def fft_case_strategy(st: Any) -> Any:
    @st.composite
    def _build(draw: Any) -> dict[str, object]:
        sample_rate_hz = draw(st.integers(min_value=32, max_value=4096))
        fft_n = draw(st.sampled_from((32, 64, 128, 256, 512)))
        spectrum_min_hz = draw(
            st.floats(
                min_value=0.0, max_value=40.0, allow_nan=False, allow_infinity=False
            )
        )
        max_band_hz = max(float(sample_rate_hz) / 2.0, spectrum_min_hz + 1.0)
        spectrum_max_hz = draw(
            st.floats(
                min_value=max(spectrum_min_hz + 0.1, 1.0),
                max_value=max_band_hz,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        spike_filter_enabled = draw(st.booleans())
        spike_col = draw(st.integers(min_value=0, max_value=fft_n - 1))
        spike_axis = draw(st.integers(min_value=0, max_value=2))
        dc_offset = draw(
            st.floats(
                min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False
            )
        )
        base_block = draw(
            st.lists(
                st.lists(
                    st.floats(
                        min_value=-8.0,
                        max_value=8.0,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                    min_size=fft_n,
                    max_size=fft_n,
                ),
                min_size=3,
                max_size=3,
            )
        )
        spike_value = draw(
            st.floats(
                min_value=-64.0, max_value=64.0, allow_nan=False, allow_infinity=False
            )
        )
        return {
            "sample_rate_hz": sample_rate_hz,
            "fft_n": fft_n,
            "spectrum_min_hz": spectrum_min_hz,
            "spectrum_max_hz": spectrum_max_hz,
            "spike_filter_enabled": spike_filter_enabled,
            "spike_col": spike_col,
            "spike_axis": spike_axis,
            "dc_offset": dc_offset,
            "base_block": base_block,
            "spike_value": spike_value,
        }

    return _build()


def processor_case_strategy(st: Any) -> Any:
    @st.composite
    def _build(draw: Any) -> dict[str, object]:
        sample_rate_hz = draw(st.integers(min_value=64, max_value=800))
        waveform_seconds = draw(st.integers(min_value=1, max_value=4))
        waveform_display_hz = draw(st.integers(min_value=1, max_value=120))
        fft_n = draw(st.sampled_from((32, 64, 128, 256)))
        spectrum_min_hz = draw(
            st.floats(
                min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False
            )
        )
        spectrum_max_hz = draw(
            st.floats(
                min_value=max(spectrum_min_hz + 0.5, 5.0),
                max_value=min(float(sample_rate_hz) / 2.0, 250.0),
                allow_nan=False,
                allow_infinity=False,
            )
        )
        accel_scale = draw(
            st.one_of(
                st.none(),
                st.floats(
                    min_value=1e-5,
                    max_value=0.05,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            )
        )
        clients = draw(
            st.lists(
                st.from_regex(r"[a-z][a-z0-9_-]{1,10}", fullmatch=True),
                min_size=1,
                max_size=3,
                unique=True,
            )
        )
        chunks: list[dict[str, object]] = []
        for client_id in clients:
            chunk_count = draw(st.integers(min_value=1, max_value=3))
            t0_us = 1_000_000
            for _ in range(chunk_count):
                row_count = draw(st.integers(min_value=0, max_value=fft_n * 2))
                rows = draw(
                    st.lists(
                        st.lists(
                            st.floats(
                                min_value=-32.0,
                                max_value=32.0,
                                allow_nan=False,
                                allow_infinity=False,
                            ),
                            min_size=3,
                            max_size=3,
                        ),
                        min_size=row_count,
                        max_size=row_count,
                    )
                )
                sample_rate_override = draw(
                    st.one_of(st.none(), st.integers(min_value=1, max_value=4096))
                )
                include_t0 = draw(st.booleans())
                t0_increment = draw(st.integers(min_value=0, max_value=500_000))
                if include_t0:
                    t0_us += t0_increment
                chunks.append(
                    {
                        "client_id": client_id,
                        "rows": rows,
                        "sample_rate_hz": sample_rate_override,
                        "t0_us": t0_us if include_t0 else None,
                    }
                )
        return {
            "sample_rate_hz": sample_rate_hz,
            "waveform_seconds": waveform_seconds,
            "waveform_display_hz": waveform_display_hz,
            "fft_n": fft_n,
            "spectrum_min_hz": spectrum_min_hz,
            "spectrum_max_hz": spectrum_max_hz,
            "accel_scale_g_per_lsb": accel_scale,
            "clients": clients,
            "chunks": chunks,
        }

    return _build()


def make_freq_slice(length: int, *, start_hz: float, step_hz: float) -> list[float]:
    return [start_hz + (step_hz * idx) for idx in range(length)]
