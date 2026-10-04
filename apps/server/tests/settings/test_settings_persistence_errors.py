"""A failed settings write is reported and leaves settings unchanged; code bugs are not hidden."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.common.exceptions import PersistenceError
from vibesensor.history.history_db import HistoryDB
from vibesensor.settings.services import build_settings_services


@pytest.mark.parametrize(
    ("error", "expected_type", "match"),
    [
        pytest.param(
            sqlite3.OperationalError("disk I/O error"),
            PersistenceError,
            "Failed to persist",
            id="sqlite-error-wrapped",
        ),
        pytest.param(OSError("disk full"), PersistenceError, "Failed to persist", id="os-error"),
        pytest.param(TypeError("bad argument type"), TypeError, "bad argument", id="type-error"),
        pytest.param(AttributeError("no such method"), AttributeError, "no such", id="attr-error"),
    ],
)
def test_failed_settings_write_keeps_the_previous_settings(
    tmp_path: Path,
    error: BaseException,
    expected_type: type[BaseException],
    match: str,
) -> None:
    services = build_settings_services(db=HistoryDB(tmp_path / "test.db"))
    before = services.car_settings.get_cars()

    with (
        patch.object(HistoryDB, "set_settings_snapshot", side_effect=error),
        pytest.raises(expected_type, match=match),
    ):
        services.car_settings.add_car({"name": "Test"})

    assert services.car_settings.get_cars() == before
