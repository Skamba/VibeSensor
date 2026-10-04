"""Which sensor location an order finding points at (``summarize_order_match_locations``).

Edge cases the simulator benchmark does not reach: a cabin sensor reading the
wheel order louder than the wheel sensor, and two corners within a near tie.
"""

from __future__ import annotations

from typing import Any

from test_support.core import (
    ALL_WHEEL_SENSORS,
    assert_summary_sections,
    assert_top_cause_contract,
    standard_metadata,
    wheel_hz,
)
from test_support.synthetic_samples import make_sample

from vibesensor.analysis.location_analysis import summarize_order_match_locations
from vibesensor.analysis.summarize import summarize_run_data
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


def test_a_wheel_sensor_that_drops_out_and_rejoins_does_not_move_the_fault() -> None:
    samples: list[dict[str, Any]] = []
    whz = wheel_hz(80.0)
    for i in range(40):
        for sensor in ALL_WHEEL_SENSORS:
            if sensor == "rear-left" and 10 <= i < 20:
                continue
            if sensor == "front-right":
                peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                vib_db = 26.0
            else:
                peaks = [{"hz": 142.5, "amp": 0.003}]
                vib_db = 8.0
            samples.append(
                make_sample(
                    t_s=float(i),
                    speed_kmh=80.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=0.003,
                ),
            )
    summary = summarize_run_data(
        standard_metadata(),
        samples,
        lang="en",
        file_name="rejoin_test",
    )
    assert_summary_sections(summary, min_top_causes=1)
    assert_top_cause_contract(
        summary["top_causes"][0],
        expected_source="wheel",
        expected_location="front-right",
    )
