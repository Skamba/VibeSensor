from __future__ import annotations

from vibesensor_core.vibration_strength import vibration_strength_db_scalar


def canonical_vibration_db(*, peak_band_rms_amp_g: float, floor_amp_g: float) -> float:
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak_band_rms_amp_g,
        floor_amp_g=floor_amp_g,
    )
