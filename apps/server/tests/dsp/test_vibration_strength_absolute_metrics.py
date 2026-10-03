from __future__ import annotations

from vibesensor.dsp.vibration_strength import compute_vibration_strength_db

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
