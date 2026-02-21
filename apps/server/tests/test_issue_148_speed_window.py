from __future__ import annotations

from vibesensor.report.findings import _speed_breakdown
from vibesensor.report.test_plan import _location_speedbin_summary


def test_location_speed_window_handles_boundary_straddle() -> None:
    matches = [
        {"speed_kmh": 74.0, "amp": 0.005, "location": "Front Left"},
        {"speed_kmh": 75.0, "amp": 0.005, "location": "Front Left"},
        {"speed_kmh": 76.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 77.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 78.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 79.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 80.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 81.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 82.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 83.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 84.0, "amp": 0.005, "location": "Front Left"},
    ]

    _, hotspot = _location_speedbin_summary(matches, lang="en")

    assert hotspot is not None
    speed_range = str(hotspot.get("speed_range") or "")
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
