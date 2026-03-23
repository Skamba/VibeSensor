from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from vibesensor.app import container as container_module


def test_create_history_db_skips_stale_recovery_when_quick_check_marked_corrupted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recovered = {"called": False}
    fake_db = SimpleNamespace(
        corruption_detected=True,
        recover_stale_recording_runs=lambda: recovered.__setitem__("called", True),
    )

    def _fake_history_db(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_db

    monkeypatch.setattr(container_module, "HistoryDB", _fake_history_db)
    config = SimpleNamespace(
        logging=SimpleNamespace(history_db_path=tmp_path / "history.db"),
    )

    result = container_module.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )

    assert result is fake_db
    assert recovered["called"] is False
