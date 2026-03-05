"""Strength bucketing and combined-spectrum runtime regressions:
- combined spectrum not polluted by zeroed amp_for_peaks
- order tolerance scales with path_compliance
- _noise_floor no double bin removal
- bucket_for_strength returns 'l0' for negative dB
- dead db_value variable removed from _top_strength_values
"""

from __future__ import annotations

import inspect
import re

from vibesensor.processing.fft import compute_fft_spectrum


class TestCombinedSpectrumNotZeroed:
    """Regression: axis_amp_slices must use amp_slice (original), not
    amp_for_peaks (which has DC bin zeroed). Otherwise the combined
    spectrum inherits the artificial zero."""

    def test_amp_slice_used_not_amp_for_peaks(self) -> None:
        """Verify source code appends amp_slice (not amp_for_peaks)
        to axis_amp_slices."""
        src = inspect.getsource(compute_fft_spectrum)
        # Find the line that appends to axis_amp_slices
        match = re.search(r"axis_amp_slices\.append\((\w+)\)", src)
        assert match is not None, "axis_amp_slices.append() not found"
        appended_var = match.group(1)
        assert appended_var == "amp_slice", (
            f"Expected axis_amp_slices.append(amp_slice), "
            f"got axis_amp_slices.append({appended_var})"
        )
