"""Guard packaged server runtime data copies against drift from canonical sources."""

from __future__ import annotations

from _paths import SERVER_ROOT


def test_packaged_runtime_data_matches_canonical_source() -> None:
    canonical_dir = SERVER_ROOT / "data"
    packaged_dir = SERVER_ROOT / "vibesensor" / "data"

    for file_name in ("report_i18n.json", "car_library.json"):
        assert (packaged_dir / file_name).read_bytes() == (canonical_dir / file_name).read_bytes()
