"""Shared sample/strength metric helpers for diagnostics."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from vibesensor.analysis.constants import MEMS_NOISE_FLOOR_G
from vibesensor.dsp.vibration_strength import percentile

if TYPE_CHECKING:
    from vibesensor.analysis.drive_table import DriveTable


def _sensor_limit_g(sensor_model: object) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    if "adxl345" in sensor_model.lower():
        return 16.0
    return None


def _floor_from_peaks(peak_amps: Sequence[float]) -> float | None:
    """A sample's floor from its analysed peaks' amplitudes: the quiet end of three or more."""
    ordered = sorted(amp for amp in peak_amps if amp > 0)
    if len(ordered) < 3:
        return None
    floor_from_peaks = float(percentile(ordered, 0.20))
    return floor_from_peaks if floor_from_peaks > 0 else None


def _run_noise_baseline_g(table: DriveTable) -> float | None:
    """Estimate run-level noise baseline as median of per-sample floor estimates."""
    floors = table.floor_amp_g[table.has_floor]
    if not floors.size:
        return None
    return float(percentile(sorted(floors.tolist()), 0.50))


def _effective_baseline_floor(
    run_noise_baseline_g: float | None,
    *,
    extra_fallback: float | None = None,
) -> float:
    """Return a safe noise-floor value for SNR computations."""
    val = (
        run_noise_baseline_g
        if run_noise_baseline_g is not None
        else (extra_fallback if extra_fallback is not None else 0.0)
    )
    return float(max(float(MEMS_NOISE_FLOOR_G), float(val)))
