"""Focused SpeedSource, SensorPlacement, and Sensor behavior contracts."""

from __future__ import annotations

import pytest

from vibesensor.domain import Sensor, SensorPlacement, SpeedSource, SpeedSourceKind


@pytest.mark.parametrize(
    ("kind", "manual_speed_kmh", "expected_label", "expected_live"),
    [
        (SpeedSourceKind.GPS, None, "GPS", True),
        (SpeedSourceKind.OBD2, None, "OBD-II", True),
        (SpeedSourceKind.MANUAL, 88.0, "Manual", False),
    ],
)
def test_speed_source_supported_kinds_follow_public_contract(
    kind: SpeedSourceKind,
    manual_speed_kmh: float | None,
    expected_label: str,
    expected_live: bool,
) -> None:
    source = SpeedSource(kind=kind, manual_speed_kmh=manual_speed_kmh)

    assert source.kind is kind
    assert source.label == expected_label
    assert source.is_live is expected_live
    assert source.is_gps is (kind is SpeedSourceKind.GPS)
    assert source.is_obd2 is (kind is SpeedSourceKind.OBD2)
    assert source.is_manual is (kind is SpeedSourceKind.MANUAL)
    if kind is SpeedSourceKind.MANUAL:
        assert source.effective_speed_kmh == pytest.approx(88.0)
    else:
        assert source.effective_speed_kmh is None


@pytest.mark.parametrize(
    ("manual_speed_kmh",),
    [
        (None,),
        (0.0,),
        (-10.0,),
    ],
)
def test_speed_source_manual_contract_rejects_missing_or_non_positive_speed(
    manual_speed_kmh: float | None,
) -> None:
    with pytest.raises(ValueError, match="manual_speed_kmh"):
        SpeedSource(kind="manual", manual_speed_kmh=manual_speed_kmh)


def test_speed_source_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        SpeedSource(kind="satnav")


@pytest.mark.parametrize(
    ("code", "expected_label"),
    [
        ("front_left_wheel", "Front Left Wheel"),
        ("engine_bay", "Engine Bay"),
        ("custom_spot", "Custom Spot"),
    ],
)
def test_sensor_placement_from_code_maps_known_and_custom_locations(
    code: str,
    expected_label: str,
) -> None:
    placement = SensorPlacement.from_code(code)

    assert placement.code == code
    assert placement.label == expected_label
    assert placement.display_name == expected_label


def test_sensor_placement_fallback_formats_unknown_casing_without_rewriting_code() -> None:
    placement = SensorPlacement.from_code("Rear_Subframe")

    assert placement.code == "Rear_Subframe"
    assert placement.label == "Rear Subframe"
    assert placement.display_name == "Rear Subframe"


def test_sensor_placement_rejects_blank_code() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        SensorPlacement(code="  ")


def test_sensor_contract_tracks_unplaced_and_placed_state() -> None:
    unplaced = Sensor(sensor_id="aabbccddeeff", name="Cabin")
    placed = Sensor(
        sensor_id="112233445566",
        placement=SensorPlacement.from_code("rear_subframe"),
    )

    assert unplaced.display_name == "Cabin"
    assert not unplaced.is_placed
    assert unplaced.location_code == ""
    assert placed.display_name == "112233445566"
    assert placed.is_placed
    assert placed.location_code == "rear_subframe"
    assert placed.placement is not None
    assert placed.placement.display_name == "Rear Subframe"


def test_sensor_from_location_codes_builds_roundtrip_ready_domain_objects() -> None:
    sensors = Sensor.from_location_codes(["front_left_wheel", "custom_spot"])

    assert sensors == (
        Sensor(
            sensor_id="front_left_wheel",
            placement=SensorPlacement(code="front_left_wheel", label="Front Left Wheel"),
        ),
        Sensor(
            sensor_id="custom_spot",
            placement=SensorPlacement(code="custom_spot", label="Custom Spot"),
        ),
    )
