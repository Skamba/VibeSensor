"""Guard: source and packaged scripted-scenario resources stay byte-for-byte aligned."""

from __future__ import annotations

from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_DATA_DIR = _SERVER_ROOT / "data" / "scripted_scenarios"
_PACKAGED_DATA_DIR = _SERVER_ROOT / "vibesensor" / "data" / "scripted_scenarios"


def _relative_yaml_paths(root: Path) -> list[Path]:
    return sorted(path.relative_to(root) for path in root.glob("*.yaml"))


def test_scripted_scenario_resource_file_sets_match() -> None:
    assert _relative_yaml_paths(_SOURCE_DATA_DIR) == _relative_yaml_paths(_PACKAGED_DATA_DIR)


def test_scripted_scenario_resource_contents_match() -> None:
    for relative_path in _relative_yaml_paths(_SOURCE_DATA_DIR):
        assert (_SOURCE_DATA_DIR / relative_path).read_text(encoding="utf-8") == (
            _PACKAGED_DATA_DIR / relative_path
        ).read_text(encoding="utf-8")
