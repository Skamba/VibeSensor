"""Focused startup-maintenance coverage for history DB container wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibesensor.app import composition as history_composition


class _RecordingHistoryDB:
    """Records startup maintenance calls in order; optionally fails summary pruning."""

    def __init__(self, *, corrupted: bool, prune_error: Exception | None = None) -> None:
        self.corruption_detected = corrupted
        self.calls: list[tuple[str, int | None]] = []
        self._prune_error = prune_error

    def recover_interrupted_runs(self) -> list[str]:
        self.calls.append(("recover", None))
        return []

    def prune_oldest_runs_for_free_space(
        self, min_free_bytes: int, *, disk_free_bytes: object
    ) -> list[str]:
        assert callable(disk_free_bytes)
        self.calls.append(("prune", min_free_bytes))
        if self._prune_error is not None:
            raise self._prune_error
        return ["oldest", "next-oldest"]


def _create_history_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    corrupted: bool = False,
    prune_error: Exception | None = None,
) -> tuple[object, _RecordingHistoryDB]:
    fake_history = _RecordingHistoryDB(corrupted=corrupted, prune_error=prune_error)

    def _fake_history_db(_path: Path, *, corruption_reporter=None) -> _RecordingHistoryDB:
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(history_composition, "HistoryDB", _fake_history_db)
    config = SimpleNamespace(
        logging=SimpleNamespace(history_db_path=tmp_path / "history.db"),
    )
    result = history_composition.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )
    return result, fake_history


def test_create_history_db_skips_stale_recovery_when_quick_check_marked_corrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, fake_history = _create_history_db(tmp_path, monkeypatch, corrupted=True)

    assert result is fake_history
    assert fake_history.calls == []


def test_create_history_db_recovers_then_prunes_on_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, fake_history = _create_history_db(tmp_path, monkeypatch)

    assert result is fake_history
    assert fake_history.calls == [
        ("recover", None),
        ("prune", history_composition.RUN_HISTORY_MIN_FREE_BYTES),
    ]


def test_create_history_db_continues_when_retention_prune_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        result, fake_history = _create_history_db(
            tmp_path,
            monkeypatch,
            prune_error=sqlite3.OperationalError("prune failed"),
        )

    assert result is fake_history
    assert "Failed to free disk space for the run history at startup" in caplog.text
