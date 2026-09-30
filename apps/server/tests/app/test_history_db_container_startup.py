"""Focused startup-maintenance coverage for history DB container wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibesensor.app.composition import history as history_composition


class _RecordingRunRepository:
    """Records startup maintenance calls in order; optionally fails summary pruning."""

    def __init__(self, *, prune_error: Exception | None = None) -> None:
        self.calls: list[tuple[str, int | None]] = []
        self._prune_error = prune_error

    def recover_stale_recording_runs(self) -> int:
        self.calls.append(("recover", None))
        return 0

    def prune_raw_capture_artifacts_older_than_days(self, days: int) -> int:
        self.calls.append(("raw", days))
        return 1

    def prune_terminal_runs_older_than_days(self, days: int) -> int:
        self.calls.append(("summary", days))
        if self._prune_error is not None:
            raise self._prune_error
        return 2


def _create_history_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    corrupted: bool = False,
    run_retention_days: int = 7,
    raw_capture_retention_days: int = 7,
    prune_error: Exception | None = None,
) -> tuple[object, SimpleNamespace, _RecordingRunRepository]:
    repository = _RecordingRunRepository(prune_error=prune_error)
    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=corrupted),
        run_repository=repository,
    )

    def _fake_history_adapters(
        _path: Path,
        *,
        corruption_reporter=None,
        engine_failure_reporter=None,
    ):
        assert corruption_reporter is not None
        assert engine_failure_reporter is None or callable(engine_failure_reporter)
        return fake_history

    monkeypatch.setattr(
        history_composition,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(
            history_db_path=tmp_path / "history.db",
            run_retention_days=run_retention_days,
            raw_capture_retention_days=raw_capture_retention_days,
        ),
    )
    result = history_composition.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )
    return result, fake_history, repository


def test_create_history_db_skips_stale_recovery_when_quick_check_marked_corrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, fake_history, repository = _create_history_db(tmp_path, monkeypatch, corrupted=True)

    assert result is fake_history
    assert repository.calls == []


@pytest.mark.parametrize(
    ("run_retention_days", "raw_capture_retention_days", "expected_calls"),
    [
        pytest.param(
            14,
            14,
            [("recover", None), ("summary", 14)],
            id="same-retention-skips-raw-prune",
        ),
        pytest.param(
            21,
            7,
            [("recover", None), ("raw", 7), ("summary", 21)],
            id="raw-capture-pruned-before-summary-retention",
        ),
    ],
)
def test_create_history_db_recovers_then_prunes_on_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_retention_days: int,
    raw_capture_retention_days: int,
    expected_calls: list[tuple[str, int | None]],
) -> None:
    result, fake_history, repository = _create_history_db(
        tmp_path,
        monkeypatch,
        run_retention_days=run_retention_days,
        raw_capture_retention_days=raw_capture_retention_days,
    )

    assert result is fake_history
    assert repository.calls == expected_calls


def test_create_history_db_continues_when_retention_prune_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        result, fake_history, _repository = _create_history_db(
            tmp_path,
            monkeypatch,
            prune_error=sqlite3.OperationalError("prune failed"),
        )

    assert result is fake_history
    assert "Failed to prune terminal runs older than 7 day(s)" in caplog.text
