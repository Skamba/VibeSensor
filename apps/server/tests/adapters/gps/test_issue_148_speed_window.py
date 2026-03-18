from __future__ import annotations

from vibesensor.domain import OrderMatchObservation
from vibesensor.use_cases.diagnostics.findings import _speed_breakdown
from vibesensor.use_cases.diagnostics.location_analysis import _location_speedbin_summary


def _obs(speed_kmh: float, amp: float, location: str) -> OrderMatchObservation:
    return OrderMatchObservation(
        predicted_hz=100.0,
        matched_hz=100.0,
        rel_error=0.0,
        amp=amp,
        location=location,
        speed_kmh=speed_kmh,
    )


def test_location_speed_window_handles_boundary_straddle() -> None:
    matches = [
        _obs(74.0, 0.005, "Front Left"),
        _obs(75.0, 0.005, "Front Left"),
        _obs(76.0, 0.030, "Front Left"),
        _obs(77.0, 0.030, "Front Left"),
        _obs(78.0, 0.030, "Front Left"),
        _obs(79.0, 0.030, "Front Left"),
        _obs(80.0, 0.030, "Front Left"),
        _obs(81.0, 0.030, "Front Left"),
        _obs(82.0, 0.030, "Front Left"),
        _obs(83.0, 0.030, "Front Left"),
        _obs(84.0, 0.005, "Front Left"),
    ]

    _, hotspot = _location_speedbin_summary(matches, lang="en")

    assert hotspot is not None
    speed_range = hotspot.speed_range
    low_text, high_text = speed_range.replace(" km/h", "").split("-", maxsplit=1)
    low, high = float(low_text), float(high_text)
    assert 75.0 <= low <= 77.0
    assert 83.0 <= high <= 85.0
    assert speed_range not in {"70-80 km/h", "80-90 km/h"}


def test_speed_breakdown_stays_fixed_10kmh_bins() -> None:
    samples = [
        {"speed_kmh": 79.9, "strength_peak_band_rms_amp_g": 0.01},
        {"speed_kmh": 80.1, "strength_peak_band_rms_amp_g": 0.02},
    ]

    rows = _speed_breakdown(samples)
    labels = {str(row.get("speed_range") or "") for row in rows}

    assert "70-80 km/h" in labels
    assert "80-90 km/h" in labels
