"""Which sensor location an order finding points at (``summarize_order_match_locations``).

Edge cases the simulator benchmark does not reach: a cabin sensor reading the
wheel order louder than the wheel sensor, and two corners within a near tie.
"""

from __future__ import annotations

from vibesensor.analysis.location_analysis import summarize_order_match_locations
from vibesensor.domain.locations import is_wheel_location
from vibesensor.domain.order_match import OrderMatchObservation


def _obs(
    speed_kmh: float, amp: float, location: str, rel_error: float = 0.0
) -> OrderMatchObservation:
    return OrderMatchObservation(
        predicted_hz=10.0,
        matched_hz=10.0,
        rel_error=rel_error,
        amp=amp,
        location=location,
        speed_kmh=speed_kmh,
    )


def test_wheel_order_points_at_the_wheel_sensor_even_when_a_seat_reads_louder() -> None:
    matches = [
        obs
        for i in range(20)
        for obs in (
            _obs(60.0 + 2 * i, 0.08, "Driver Seat", rel_error=0.02),
            _obs(60.0 + 2 * i, 0.06, "Front Left", rel_error=0.01),
        )
    ]

    _, result = summarize_order_match_locations(matches, lang="en", suspected_source="wheel/tire")

    assert result is not None
    assert is_wheel_location(result.top_location), result.top_location


def test_near_tie_between_two_corners_is_reported_as_ambiguous() -> None:
    matches = [
        _obs(85.0, 0.0110, "Rear Right"),
        _obs(85.0, 0.0102, "Rear Left"),
        _obs(86.0, 0.0112, "Rear Right"),
        _obs(86.0, 0.0103, "Rear Left"),
    ]

    sentence, result = summarize_order_match_locations(matches, lang="en")

    assert result is not None
    assert result.ambiguous_location
    assert result.display_location == "ambiguous location: Rear Right / Rear Left"
    assert list(result.hotspot.alternative_locations) == ["Rear Right", "Rear Left"]
    assert result.localization_confidence < 0.4
    assert isinstance(sentence, dict)
    assert "ambiguous location" in str(sentence.get("location", ""))
