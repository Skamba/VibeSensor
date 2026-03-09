from __future__ import annotations

import pytest
from vibesensor_core.vibration_strength import compute_vibration_strength_db

from vibesensor.analysis.strength_labels import strength_text

# Fields every result dict must contain as floats.
_AMPLITUDE_FIELDS = ("peak_amp_g", "noise_floor_amp_g")


def _assert_amplitude_fields_present(result: dict) -> None:
    """Assert that *result* contains all expected amplitude fields as floats."""
    for field in _AMPLITUDE_FIELDS:
        assert field in result, f"missing key {field!r}"
        assert isinstance(result[field], float), (
            f"{field} should be float, got {type(result[field]).__name__}"
        )


def test_compute_strength_returns_absolute_amplitude_fields() -> None:
    result = compute_vibration_strength_db(
        freq_hz=[1.0, 2.0, 3.0],
        combined_spectrum_amp_g_values=[0.0, 0.0, 0.0],
    )
    _assert_amplitude_fields_present(result)
    # All-zeros: values must be near-zero and non-negative.
    for field in _AMPLITUDE_FIELDS:
        val = result[field]
        assert 0.0 <= val < 0.01, f"near-zero {field} expected, got {val}"


@pytest.mark.parametrize(
    ("db_upper", "peak_lower", "floor_lower"),
    [(1.0, 0.18, 0.17)],
    ids=["near-zero-db"],
)
def test_near_zero_db_with_meaningful_peak_is_still_labeled_in_db(
    db_upper: float,
    peak_lower: float,
    floor_lower: float,
) -> None:
    freq_hz = [float(i) for i in range(21)]
    combined = [0.03] * 6 + [0.18] * 15
    combined[12] = 0.20

    result = compute_vibration_strength_db(
        freq_hz=freq_hz,
        combined_spectrum_amp_g_values=combined,
    )
    _assert_amplitude_fields_present(result)

    assert result["vibration_strength_db"] < db_upper
    assert result["peak_amp_g"] > peak_lower
    assert result["noise_floor_amp_g"] >= floor_lower

    label = strength_text(result["vibration_strength_db"], lang="en")
    assert "dB" in label, f"expected 'dB' in label, got {label!r}"
