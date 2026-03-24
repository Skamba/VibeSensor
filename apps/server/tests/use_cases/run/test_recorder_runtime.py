from __future__ import annotations

import logging

import pytest

from vibesensor.use_cases.run import _recorder_runtime


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
async def test_idle_runtime_tick_clears_stale_tick_timeout_error(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    logger._persistence.set_last_write_error(_recorder_runtime._DB_TIMEOUT_ERROR)

    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", _raise_stop_loop)

    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(logger, logger=logging.getLogger(__name__))

    assert logger.status().write_error is None


@pytest.mark.asyncio
async def test_idle_runtime_tick_preserves_non_tick_write_error(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    logger._persistence.set_last_write_error("history append_samples failed: disk full")

    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", _raise_stop_loop)

    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(logger, logger=logging.getLogger(__name__))

    assert logger.status().write_error == "history append_samples failed: disk full"


@pytest.mark.asyncio
async def test_runtime_auto_stop_uses_to_thread(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None

    monkeypatch.setattr(logger._sample_flush, "build_sample_records", lambda **_: [])
    monkeypatch.setattr(logger._sample_flush, "append_records", lambda *args, **kwargs: True)

    stop_calls: list[tuple[str, str]] = []

    def fake_stop_recording(
        *,
        _only_if_run_id: str | None = None,
        reason: str = "manual",
    ):
        assert _only_if_run_id is not None
        stop_calls.append((_only_if_run_id, reason))
        logger._lifecycle.stop()
        return logger.status()

    monkeypatch.setattr(logger, "stop_recording", fake_stop_recording)

    to_thread_calls: list[object] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(_recorder_runtime.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", _raise_stop_loop)

    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(logger, logger=logging.getLogger(__name__))

    assert stop_calls == [(snapshot.run_id, "no_data_timeout")]
    assert fake_stop_recording in to_thread_calls


@pytest.mark.asyncio
async def test_runtime_tick_releases_lock_before_build_and_append(
    make_logger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger()
    logger.start_recording()

    build_lock_owned: list[bool] = []
    append_lock_owned: list[bool] = []

    def fake_build_sample_records(**_kwargs):
        build_lock_owned.append(logger._lock._is_owned())
        return []

    def fake_append_records(*_args, **_kwargs) -> bool:
        append_lock_owned.append(logger._lock._is_owned())
        return False

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(logger._sample_flush, "build_sample_records", fake_build_sample_records)
    monkeypatch.setattr(logger._sample_flush, "append_records", fake_append_records)
    monkeypatch.setattr(_recorder_runtime.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(_recorder_runtime.asyncio, "sleep", _raise_stop_loop)

    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(logger, logger=logging.getLogger(__name__))

    assert build_lock_owned == [False]
    assert append_lock_owned == [False]
