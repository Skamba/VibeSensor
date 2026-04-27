"""Guard canonical packaged server static data files exist."""

from __future__ import annotations

from _paths import SERVER_ROOT


def test_packaged_runtime_data_matches_canonical_source() -> None:
    packaged_dir = SERVER_ROOT / "vibesensor" / "data"

    assert (packaged_dir / "report_i18n.json").is_file()
    vehicle_config_dir = packaged_dir / "vehicle_configurations"
    assert vehicle_config_dir.is_dir()
    assert any(vehicle_config_dir.rglob("*.json"))
    assert not (packaged_dir / "vehicle_configurations.json").exists()
