"""EXPERIMENT: numba kernel for ``window_spectrum.line_reads``' stacked reads (64-bit only).

The same floating-point steps as ``_stacked_line_reads`` and ``_python_sum``, read by
read: no fastmath, so no reassociation or contraction into fused multiply-adds.
"""

from __future__ import annotations

import math

import numba
import numpy as np


@numba.njit(cache=True, nogil=True, error_model="numpy")
def _neumaier(values, count):  # noqa: ANN001, ANN202
    total = 0.0 + values[0]
    compensation = 0.0
    for k in range(1, count):
        value = values[k]
        step = total + value
        if abs(total) >= abs(value):
            compensation += (total - step) + value
        else:
            compensation += (value - step) + total
        total = step
    if compensation != 0.0 and math.isfinite(compensation):
        return total + compensation
    return total


@numba.njit(cache=True, nogil=True, error_model="numpy")
def stacked_reads(  # noqa: PLR0913
    rows,
    row,
    centre,
    half,
    target,
    flank_bins,
    band_bins,
    mean_distance,
    spread,
    spread_squares,
    excess,
    flanks,
):  # noqa: ANN001, ANN201
    """Each read's excess and flanks into *excess*/*flanks* at *target*."""
    max_half = half.max() if half.size else 0
    power = np.empty(2 * max_half + 1 + 2 * flank_bins)
    side = np.empty(2 * flank_bins)
    paired = np.empty(flank_bins)
    terms = np.empty(max(flank_bins, 2 * max_half + 1))
    for i in range(row.size):
        h = half[i]
        width = 2 * h + 1 + 2 * flank_bins
        first = centre[i] - h - flank_bins
        r = row[i]
        for k in range(width):
            value = np.float64(rows[r, first + k])
            power[k] = value * value
        for k in range(flank_bins):
            side[k] = power[k]
            side[flank_bins + k] = power[width - flank_bins + k]
        read_flanks = _neumaier(side, 2 * flank_bins) / (2 * flank_bins)
        for k in range(2 * h + 1):
            terms[k] = power[flank_bins + k]
        band = _neumaier(terms, 2 * h + 1)
        for j in range(flank_bins):
            paired[j] = 0.5 * (power[flank_bins - 1 - j] + power[width - flank_bins + j])
        mean_paired = _neumaier(paired, flank_bins) / flank_bins
        for j in range(flank_bins):
            terms[j] = spread[h, j] * (paired[j] - mean_paired)
        bend = _neumaier(terms, flank_bins) / spread_squares[h]
        level = mean_paired - bend * mean_distance[h]
        under = (2 * h + 1) * level + bend * h * (h + 1) * (2 * h + 1) / 3.0
        excess[target[i]] = (band - under) / band_bins
        flanks[target[i]] = read_flanks
