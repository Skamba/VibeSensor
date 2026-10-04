"""Tests for #302: ensure analysis completes before DB close on shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from vibesensor.analysis.post_analysis import PostAnalysisWorker
from vibesensor.history.history_db import HistoryDB


@pytest.mark.asyncio
async def test_shutdown_waits_for_analysis_before_db_close(tmp_path: Path, monkeypatch) -> None:
    """Integration: stop_runtime waits for analysis, then closes DB — not before."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {"history_db_path": str(tmp_path / "history.db")},
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")

    from vibesensor.app import bootstrap as bootstrap_mod

    async def _fake_start(self):
        return None

    events: list[str] = []

    original_close = HistoryDB.close

    def _tracking_close(self: HistoryDB) -> None:
        events.append("db_close")
        original_close(self)

    original_wait = PostAnalysisWorker.wait

    def _tracking_wait(self, timeout_s=30.0):
        result = original_wait(self, timeout_s)
        events.append("analysis_wait_done")
        return result

    monkeypatch.setattr(bootstrap_mod.LifecycleManager, "start", _fake_start)
    monkeypatch.setattr(HistoryDB, "close", _tracking_close)
    monkeypatch.setattr(PostAnalysisWorker, "wait", _tracking_wait)

    app = await asyncio.to_thread(bootstrap_mod.create_app, config_path=cfg_path)
    async with app.router.lifespan_context(app):
        pass

    # The key assertion: analysis_wait_done must appear BEFORE db_close
    assert events.index("analysis_wait_done") < events.index("db_close"), (
        f"Expected analysis to finish before DB close, got: {events}"
    )
