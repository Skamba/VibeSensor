"""Focused startup-maintenance coverage for history DB container wiring."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from vibesensor.app import container as container_module


def test_create_history_db_skips_stale_recovery_when_quick_check_marked_corrupted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recovered = {"called": False}
    pruned = {"called": False}
    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=True),
        run_repository=SimpleNamespace(
            recover_stale_recording_runs=lambda: recovered.__setitem__("called", True),
            prune_raw_capture_artifacts_older_than_days=lambda _days: pruned.__setitem__(
                "called",
                True,
            ),
            prune_terminal_runs_older_than_days=lambda _days: pruned.__setitem__("called", True),
        ),
    )

    def _fake_history_adapters(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(
        container_module,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(
            history_db_path=tmp_path / "history.db",
            run_retention_days=7,
            raw_capture_retention_days=7,
        ),
    )

    result = container_module.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )

    assert result is fake_history
    assert recovered["called"] is False
    assert pruned["called"] is False


def test_create_history_db_prunes_old_terminal_runs_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    def _recover() -> int:
        calls.append(("recover", None))
        return 0

    def _prune(days: int) -> int:
        calls.append(("prune", days))
        return 2

    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=False),
        run_repository=SimpleNamespace(
            recover_stale_recording_runs=_recover,
            prune_raw_capture_artifacts_older_than_days=lambda _days: 0,
            prune_terminal_runs_older_than_days=_prune,
        ),
    )

    def _fake_history_adapters(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(
        container_module,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(
            history_db_path=tmp_path / "history.db",
            run_retention_days=14,
            raw_capture_retention_days=14,
        ),
    )

    result = container_module.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )

    assert result is fake_history
    assert calls == [("recover", None), ("prune", 14)]


def test_create_history_db_prunes_raw_capture_before_summary_retention_when_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=False),
        run_repository=SimpleNamespace(
            recover_stale_recording_runs=lambda: calls.append(("recover", None)) or 0,
            prune_raw_capture_artifacts_older_than_days=lambda days: (
                calls.append(("raw", days)) or 1
            ),
            prune_terminal_runs_older_than_days=lambda days: calls.append(("summary", days)) or 0,
        ),
    )

    def _fake_history_adapters(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(
        container_module,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(
            history_db_path=tmp_path / "history.db",
            run_retention_days=21,
            raw_capture_retention_days=7,
        ),
    )

    result = container_module.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )

    assert result is fake_history
    assert calls == [("recover", None), ("raw", 7), ("summary", 21)]


def test_create_history_db_continues_when_retention_prune_fails(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=False),
        run_repository=SimpleNamespace(
            recover_stale_recording_runs=lambda: 0,
            prune_raw_capture_artifacts_older_than_days=lambda _days: 0,
            prune_terminal_runs_older_than_days=lambda _days: (_ for _ in ()).throw(
                sqlite3.OperationalError("prune failed")
            ),
        ),
    )

    def _fake_history_adapters(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(
        container_module,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(
            history_db_path=tmp_path / "history.db",
            run_retention_days=7,
            raw_capture_retention_days=7,
        ),
    )

    with caplog.at_level("WARNING"):
        result = container_module.create_history_db(
            config,
            corruption_reporter=lambda _details: None,
        )

    assert result is fake_history
    assert "Failed to prune terminal runs older than 7 day(s)" in caplog.text
