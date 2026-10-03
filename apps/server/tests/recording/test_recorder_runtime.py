from __future__ import annotations

import logging

import pytest

from vibesensor.recording import _recorder_runtime


class _StopLoop(BaseException):
    pass


async def _raise_stop_loop(_seconds: float) -> None:
    raise _StopLoop


@pytest.mark.asyncio
async def test_idle_runtime_tick_does_not_create_phantom_run(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=fake_history_db)
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 5

    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", _raise_stop_loop)

    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(logger, logger=logging.getLogger(__name__))

    status = logger.status()
    assert status.enabled is False
    assert status.run_id is None
    assert fake_history_db.create_calls == []
    assert fake_history_db.append_calls == []


@pytest.mark.asyncio
async def test_runtime_auto_stops_a_run_at_the_thirty_minute_limit(
    make_logger,
    fake_history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=fake_history_db)
    monkeypatch.setattr(logger.post_analysis, "schedule", lambda _run_id: None)
    started = logger.start_recording()
    snapshot = logger._lifecycle.snapshot()
    assert snapshot is not None
    logger._sample_flush._monotonic = lambda: snapshot.start_mono_s + 30 * 60 + 1.0

    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", _raise_stop_loop)
    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(logger, logger=logging.getLogger(__name__))

    status = logger.status()
    assert started.enabled is True
    assert status.enabled is False
    assert status.last_stop_reason == "max_duration"
