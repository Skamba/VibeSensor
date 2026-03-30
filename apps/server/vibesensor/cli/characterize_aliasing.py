from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np

from vibesensor.app.config_defaults import documented_default_config
from vibesensor.infra.processing.compute import SignalMetricsComputer
from vibesensor.infra.processing.models import ProcessorConfig
from vibesensor.shared.constants.dsp import FFT_N, SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.types.json_types import JsonObject

DEFAULT_MAX_INPUT_HZ = 2400.0
DEFAULT_INTERVAL_STEP_HZ = 1.0


@dataclass(frozen=True)
class AliasInterval:
    input_start_hz: float
    input_end_hz: float

    @property
    def alias_start_hz(self) -> float:
        return min(
            alias_frequency_hz(self.input_start_hz, self.sample_rate_hz),
            alias_frequency_hz(self.input_end_hz, self.sample_rate_hz),
        )

    @property
    def alias_end_hz(self) -> float:
        return max(
            alias_frequency_hz(self.input_start_hz, self.sample_rate_hz),
            alias_frequency_hz(self.input_end_hz, self.sample_rate_hz),
        )

    @property
    def sample_rate_hz(self) -> float:
        return self._sample_rate_hz

    _sample_rate_hz: float


@dataclass(frozen=True)
class ExampleResult:
    input_hz: float
    theoretical_alias_hz: float
    alias_in_analysis_band: bool
    detected_peak_hz: float | None
    detected_peak_amp_g: float


def _default_config() -> JsonObject:
    return documented_default_config()


def parse_args() -> argparse.Namespace:
    defaults = _default_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-rate-hz",
        type=int,
        default=int(defaults["processing"]["sample_rate_hz"]),
        help="Input sample rate to characterize (default: current runtime default).",
    )
    parser.add_argument(
        "--fft-n",
        type=int,
        default=FFT_N,
        help="FFT size used by the live chain (default: current constant).",
    )
    parser.add_argument(
        "--spectrum-min-hz",
        type=float,
        default=SPECTRUM_MIN_HZ,
        help="Lower analysis-band frequency (default: current constant).",
    )
    parser.add_argument(
        "--spectrum-max-hz",
        type=float,
        default=SPECTRUM_MAX_HZ,
        help="Upper analysis-band frequency (default: current constant).",
    )
    parser.add_argument(
        "--max-input-hz",
        type=float,
        default=DEFAULT_MAX_INPUT_HZ,
        help="Upper bound for the fold-back interval scan (default: 2400 Hz).",
    )
    parser.add_argument(
        "--interval-step-hz",
        type=float,
        default=DEFAULT_INTERVAL_STEP_HZ,
        help="Scan step used when grouping fold-back intervals (default: 1 Hz).",
    )
    return parser.parse_args()


def alias_frequency_hz(input_hz: float, sample_rate_hz: float) -> float:
    """Fold *input_hz* into the [0, fs/2] alias band for sample rate *fs*."""
    fs = float(sample_rate_hz)
    nyquist = fs * 0.5
    return abs(((float(input_hz) + nyquist) % fs) - nyquist)


def find_alias_intervals(
    *,
    sample_rate_hz: float,
    spectrum_min_hz: float,
    spectrum_max_hz: float,
    max_input_hz: float,
    step_hz: float,
) -> list[AliasInterval]:
    """Return out-of-band input-frequency intervals that fold into the analysis band."""
    nyquist = sample_rate_hz * 0.5
    intervals: list[AliasInterval] = []
    f_hz = nyquist + step_hz
    active_start: float | None = None
    prev_hz: float | None = None
    while f_hz <= max_input_hz + (step_hz * 0.5):
        alias_hz = alias_frequency_hz(f_hz, sample_rate_hz)
        in_band = spectrum_min_hz <= alias_hz <= spectrum_max_hz
        if in_band and active_start is None:
            active_start = f_hz
        elif (not in_band) and active_start is not None and prev_hz is not None:
            intervals.append(
                AliasInterval(
                    input_start_hz=active_start,
                    input_end_hz=prev_hz,
                    _sample_rate_hz=sample_rate_hz,
                ),
            )
            active_start = None
        prev_hz = f_hz
        f_hz += step_hz

    if active_start is not None and prev_hz is not None:
        intervals.append(
            AliasInterval(
                input_start_hz=active_start,
                input_end_hz=prev_hz,
                _sample_rate_hz=sample_rate_hz,
            ),
        )
    return intervals


def _make_computer(
    *,
    sample_rate_hz: int,
    fft_n: int,
    spectrum_min_hz: float,
    spectrum_max_hz: float,
) -> SignalMetricsComputer:
    window_s = max(1.0, math.ceil(fft_n / max(1, sample_rate_hz)))
    return SignalMetricsComputer(
        ProcessorConfig(
            sample_rate_hz=sample_rate_hz,
            waveform_seconds=int(window_s),
            waveform_display_hz=120,
            fft_n=fft_n,
            spectrum_min_hz=spectrum_min_hz,
            spectrum_max_hz=spectrum_max_hz,
            accel_scale_g_per_lsb=None,
        ),
    )


def analyze_tone(
    *,
    computer: SignalMetricsComputer,
    input_hz: float,
    sample_rate_hz: int,
    fft_n: int,
    spectrum_min_hz: float,
    spectrum_max_hz: float,
) -> ExampleResult:
    """Run one pure tone through the current FFT chain and report the in-band peak."""
    t = np.arange(fft_n, dtype=np.float32) / np.float32(sample_rate_hz)
    tone = np.sin(np.float32(2.0 * math.pi) * np.float32(input_hz) * t).astype(np.float32)
    block = np.zeros((3, fft_n), dtype=np.float32)
    block[0, :] = tone
    result = computer.compute_fft_spectrum(
        block,
        sample_rate_hz,
        spike_filter_enabled=False,
    )
    freqs = result["freq_slice"]
    amps = result["combined_amp"]
    peak_hz: float | None = None
    peak_amp = 0.0
    if amps.size:
        idx = int(np.argmax(amps))
        peak_hz = float(freqs[idx])
        peak_amp = float(amps[idx])
    alias_hz = alias_frequency_hz(input_hz, sample_rate_hz)
    return ExampleResult(
        input_hz=input_hz,
        theoretical_alias_hz=alias_hz,
        alias_in_analysis_band=spectrum_min_hz <= alias_hz <= spectrum_max_hz,
        detected_peak_hz=peak_hz,
        detected_peak_amp_g=peak_amp,
    )


def representative_frequencies(
    *,
    sample_rate_hz: float,
    alias_intervals: list[AliasInterval],
) -> list[float]:
    """Pick a small set of representative tones for human-readable output."""
    nyquist = sample_rate_hz * 0.5
    examples: list[float] = [nyquist + 50.0]
    for interval in alias_intervals[:2]:
        midpoint = (interval.input_start_hz + interval.input_end_hz) * 0.5
        examples.extend([interval.input_start_hz, midpoint, interval.input_end_hz])
    deduped = sorted({round(value, 3) for value in examples})
    return deduped


def _fmt_hz(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def main() -> int:
    args = parse_args()
    nyquist_hz = args.sample_rate_hz * 0.5
    bin_spacing_hz = args.sample_rate_hz / args.fft_n
    alias_intervals = find_alias_intervals(
        sample_rate_hz=float(args.sample_rate_hz),
        spectrum_min_hz=float(args.spectrum_min_hz),
        spectrum_max_hz=float(args.spectrum_max_hz),
        max_input_hz=float(args.max_input_hz),
        step_hz=float(args.interval_step_hz),
    )
    computer = _make_computer(
        sample_rate_hz=int(args.sample_rate_hz),
        fft_n=int(args.fft_n),
        spectrum_min_hz=float(args.spectrum_min_hz),
        spectrum_max_hz=float(args.spectrum_max_hz),
    )
    examples = [
        analyze_tone(
            computer=computer,
            input_hz=f_hz,
            sample_rate_hz=int(args.sample_rate_hz),
            fft_n=int(args.fft_n),
            spectrum_min_hz=float(args.spectrum_min_hz),
            spectrum_max_hz=float(args.spectrum_max_hz),
        )
        for f_hz in representative_frequencies(
            sample_rate_hz=float(args.sample_rate_hz),
            alias_intervals=alias_intervals,
        )
    ]

    print("Current digital-chain alias characterization")
    print()
    print(f"sample_rate_hz     : {args.sample_rate_hz}")
    print(f"nyquist_hz         : {_fmt_hz(nyquist_hz)}")
    print(f"fft_n              : {args.fft_n}")
    print(f"fft_window_s       : {args.fft_n / args.sample_rate_hz:.3f}")
    print(f"bin_spacing_hz     : {bin_spacing_hz:.6f}")
    print(f"analysis_band_hz   : {_fmt_hz(args.spectrum_min_hz)}-{_fmt_hz(args.spectrum_max_hz)}")
    print(f"scan_max_input_hz  : {_fmt_hz(args.max_input_hz)}")
    print()
    print("Out-of-band input intervals that fold into the current analysis band:")
    if not alias_intervals:
        print("  none")
    else:
        for interval in alias_intervals:
            alias_lo = alias_frequency_hz(interval.input_start_hz, interval.sample_rate_hz)
            alias_hi = alias_frequency_hz(interval.input_end_hz, interval.sample_rate_hz)
            print(
                "  "
                f"{_fmt_hz(interval.input_start_hz)}-{_fmt_hz(interval.input_end_hz)} Hz"
                " -> aliases to "
                f"{_fmt_hz(min(alias_lo, alias_hi))}-{_fmt_hz(max(alias_lo, alias_hi))} Hz",
            )
    print()
    print("Representative tones through the current FFT path:")
    print("  input_hz  alias_hz  in_band  detected_peak_hz  detected_peak_amp_g")
    for row in examples:
        print(
            "  "
            f"{_fmt_hz(row.input_hz):>8}  "
            f"{_fmt_hz(row.theoretical_alias_hz):>8}  "
            f"{'yes' if row.alias_in_analysis_band else 'no ':>7}  "
            f"{_fmt_hz(row.detected_peak_hz):>16}  "
            f"{row.detected_peak_amp_g:>19.6f}",
        )
    print()
    print(
        "Interpretation: any unfiltered physical vibration above Nyquist that lands in the "
        "listed input intervals can appear as a false in-band peak after sampling.",
    )
    print(
        "This tool characterizes the digital chain only. Confirm the real front-end with "
        "hardware sweep tests before claiming anti-alias performance.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
