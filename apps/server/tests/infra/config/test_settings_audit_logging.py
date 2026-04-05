"""Verify settings-store audit logs capture key language and car mutations."""

from __future__ import annotations

import logging

import pytest
from test_support.settings_services import build_settings_services


def test_set_language_logs_audit_record(caplog: pytest.LogCaptureFixture) -> None:
    services = build_settings_services()

    with caplog.at_level(logging.INFO, logger="vibesensor.infra.config.ui_preferences"):
        services.ui_preferences.set_language("nl")

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
    services = build_settings_services()

    with caplog.at_level(logging.INFO, logger="vibesensor.infra.config.car_settings"):
        created = services.car_settings.add_car({"name": "Track Car", "type": "coupe"})

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
