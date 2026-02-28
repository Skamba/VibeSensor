from __future__ import annotations

from vibesensor_core.vibration_strength import compute_vibration_strength_db

from vibesensor.analysis.strength_labels import strength_text


def test_compute_strength_returns_absolute_amplitude_fields() -> None:
    result = compute_vibration_strength_db(
        freq_hz=[1.0, 2.0, 3.0],
        combined_spectrum_amp_g_values=[0.0, 0.0, 0.0],
    )
    assert "peak_amp_g" in result
    assert "noise_floor_amp_g" in result
    assert isinstance(result["peak_amp_g"], float)
    assert isinstance(result["noise_floor_amp_g"], float)


def test_near_zero_db_with_meaningful_peak_is_labeled_with_peak_amplitude() -> None:
    freq_hz = [float(i) for i in range(21)]
    combined = [0.03] * 6 + [0.18] * 15
    combined[12] = 0.20

    result = compute_vibration_strength_db(
        freq_hz=freq_hz,
        combined_spectrum_amp_g_values=combined,
    )

    assert result["vibration_strength_db"] < 1.0
    assert result["peak_amp_g"] > 0.18
    assert result["noise_floor_amp_g"] >= 0.17

    label = strength_text(
        result["vibration_strength_db"],
        lang="en",
        peak_amp_g=result["peak_amp_g"],
    )
    assert "dB" in label
    assert "g peak" in label
