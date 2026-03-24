from __future__ import annotations

import logging

import pytest

from vibesensor.infra.config.settings_store import SettingsStore


def test_set_language_logs_audit_record(caplog: pytest.LogCaptureFixture) -> None:
    store = SettingsStore()

    with caplog.at_level(logging.INFO, logger="vibesensor.infra.config.settings_store"):
        store.set_language("nl")

    record = next(
        rec
        for rec in caplog.records
        if rec.message == "settings_change"
        and getattr(rec, "settings_action", None) == "set_language"
    )
    assert record.before == "en"
    assert record.after == "nl"
    assert getattr(record, "request_id", None) is None


def test_add_car_logs_audit_record(caplog: pytest.LogCaptureFixture) -> None:
    store = SettingsStore()

    with caplog.at_level(logging.INFO, logger="vibesensor.infra.config.car_settings"):
        created = store.add_car({"name": "Track Car", "type": "coupe"})

    record = next(
        rec
        for rec in caplog.records
        if rec.message == "settings_change" and getattr(rec, "settings_action", None) == "add_car"
    )
    assert record.before is None
    assert record.after["id"] == created.cars[0]["id"]
    assert record.after["name"] == "Track Car"
    assert record.after["type"] == "coupe"
    assert record.car_id == created.cars[0]["id"]
