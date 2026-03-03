from builders import CAR_PROFILES, profile_metadata


def test_profile_metadata_returns_fresh_dict_each_call() -> None:
    profile = CAR_PROFILES[0]
    first = profile_metadata(profile)
    first["language"] = "de"

    second = profile_metadata(profile)

    assert second["language"] == "en"


def test_profile_metadata_keeps_profile_specific_values() -> None:
    profile = CAR_PROFILES[1]

    meta = profile_metadata(profile)

    assert meta["final_drive_ratio"] == profile["final_drive_ratio"]
    assert meta["current_gear_ratio"] == profile["current_gear_ratio"]
    assert meta["tire_circumference_m"] > 0
