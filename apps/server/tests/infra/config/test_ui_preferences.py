"""Focused tests for persisted UI language and speed-unit preferences."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support.settings_services import build_settings_services, write_raw_settings_snapshot

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters


def test_ui_preferences_language_roundtrip() -> None:
    services = build_settings_services()
    assert services.ui_preferences.language == "en"
    assert services.ui_preferences.set_language("nl") == "nl"
    assert services.ui_preferences.language == "nl"


def test_ui_preferences_speed_unit_roundtrip(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    services = build_settings_services(db=db.settings_snapshot_repository)
    assert services.ui_preferences.speed_unit == "kmh"

    services.ui_preferences.set_speed_unit("mps")
    assert services.ui_preferences.speed_unit == "mps"

    reloaded = build_settings_services(db=db.settings_snapshot_repository)
    assert reloaded.ui_preferences.speed_unit == "mps"


def test_ui_preferences_load_normalizes_language_and_speed_unit(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    write_raw_settings_snapshot(db.lifecycle, '{"language": " NL ", "speedUnit": " MPS "}')
    services = build_settings_services(db=db.settings_snapshot_repository)
    assert services.ui_preferences.language == "nl"
    assert services.ui_preferences.speed_unit == "mps"


def test_ui_preferences_load_whitespace_only_values_default(tmp_path: Path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    write_raw_settings_snapshot(db.lifecycle, '{"language": "   ", "speedUnit": "   "}')
    services = build_settings_services(db=db.settings_snapshot_repository)
    assert services.ui_preferences.language == "en"
    assert services.ui_preferences.speed_unit == "kmh"


def test_ui_preferences_speed_unit_invalid_raises() -> None:
    services = build_settings_services()
    with pytest.raises(ValueError, match="speed_unit"):
        services.ui_preferences.set_speed_unit("mph")


def test_ui_preferences_language_invalid_raises() -> None:
    services = build_settings_services()
    with pytest.raises(ValueError, match="language"):
        services.ui_preferences.set_language("fr")
