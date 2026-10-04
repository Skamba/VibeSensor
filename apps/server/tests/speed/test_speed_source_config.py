"""SpeedSourceConfig codec and partial updates."""

from __future__ import annotations

from vibesensor.speed.speed_source_config import SpeedSourceConfig


def test_from_dict_reads_camel_case_keys() -> None:
    config = SpeedSourceConfig.from_dict(
        {"speedSource": "manual", "manualSpeedKph": 80.0, "staleTimeoutS": 5.0}
    )
    assert (config.speed_source, config.manual_speed_kph, config.stale_timeout_s) == (
        "manual",
        80.0,
        5.0,
    )


def test_invalid_speed_source_defaults_to_gps() -> None:
    assert SpeedSourceConfig.from_dict({"speedSource": "invalid"}).speed_source == "gps"


def test_stale_timeout_clamped_to_3_120_s() -> None:
    assert SpeedSourceConfig.from_dict({"staleTimeoutS": 0.5}).stale_timeout_s == 3.0
    assert SpeedSourceConfig.from_dict({"staleTimeoutS": 9999}).stale_timeout_s == 120.0


def test_roundtrip_normalizes_the_obd_device_mac() -> None:
    config = SpeedSourceConfig.from_dict(
        {
            "speedSource": "obd2",
            "obdDeviceMac": "02:00:00:00:00:4D",
            "obdDeviceName": "OBDLink MX+ 80163",
        }
    )
    payload = config.to_dict()
    assert payload["speedSource"] == "obd2"
    assert payload["obdDeviceMac"] == "02000000004d"
    assert payload["obdDeviceName"] == "OBDLink MX+ 80163"


def test_apply_update_changes_only_the_keys_it_sends() -> None:
    config = SpeedSourceConfig.default()
    config.apply_update({"speedSource": "manual", "manualSpeedKph": 80.0})
    assert (config.speed_source, config.manual_speed_kph) == ("manual", 80.0)

    config.apply_update({"staleTimeoutS": 5})
    assert config.manual_speed_kph == 80.0, "a partial update must keep the manual speed"

    config.apply_update({"manualSpeedKph": 100.0})
    assert config.manual_speed_kph == 100.0

    config.apply_update({"speedSource": "gps", "manualSpeedKph": None})
    assert config.manual_speed_kph is None


def test_apply_update_clears_obd_name_when_mac_clears() -> None:
    config = SpeedSourceConfig.from_dict(
        {
            "speedSource": "obd2",
            "obdDeviceMac": "02:00:00:00:00:4D",
            "obdDeviceName": "OBDLink MX+ 80163",
        }
    )
    config.apply_update({"obdDeviceMac": None})
    assert config.obd_device_mac is None
    assert config.obd_device_name is None


def test_a_paired_adapter_is_the_source_until_the_user_chooses_one() -> None:
    config = SpeedSourceConfig.default()
    config.apply_update({"obdDeviceMac": "02:00:00:00:00:4D"})
    assert (config.speed_source, config.speed_source_chosen) == ("obd2", False)

    # Unpairing goes back to the default.
    config.apply_update({"obdDeviceMac": None})
    assert config.speed_source == "gps"


def test_an_explicit_choice_is_never_overridden_by_pairing() -> None:
    config = SpeedSourceConfig.default()
    config.apply_update({"speedSource": "gps"})
    config.apply_update({"obdDeviceMac": "02:00:00:00:00:4D"})

    assert (config.speed_source, config.speed_source_chosen) == ("gps", True)
    reloaded = SpeedSourceConfig.from_dict(config.to_dict())
    assert (reloaded.speed_source, reloaded.speed_source_chosen) == ("gps", True)


def test_settings_saved_before_the_choice_was_recorded() -> None:
    """GPS was the default, so a stored GPS with a paired adapter was never a choice."""
    legacy_gps = SpeedSourceConfig.from_dict(
        {"speedSource": "gps", "obdDeviceMac": "02000000004d", "staleTimeoutS": 10}
    )
    legacy_manual = SpeedSourceConfig.from_dict(
        {"speedSource": "manual", "manualSpeedKph": 80.0, "obdDeviceMac": "02000000004d"}
    )

    assert (legacy_gps.speed_source, legacy_gps.speed_source_chosen) == ("obd2", False)
    assert (legacy_manual.speed_source, legacy_manual.speed_source_chosen) == ("manual", True)
