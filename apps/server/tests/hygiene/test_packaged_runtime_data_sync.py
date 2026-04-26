"""Guard canonical packaged server static data files exist."""

from __future__ import annotations

from _paths import SERVER_ROOT


def test_packaged_runtime_data_matches_canonical_source() -> None:
    packaged_dir = SERVER_ROOT / "vibesensor" / "data"

    for file_name in ("report_i18n.json", "vehicle_configurations.json"):
        assert (packaged_dir / file_name).is_file()
