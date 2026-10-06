from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from vibesensor.recording import _recorder_runtime


class _StopLoop(BaseException):
    pass


async def _raise_stop_loop(_seconds: float) -> None:
    raise _StopLoop


@pytest.mark.asyncio
async def test_idle_runtime_tick_does_not_create_phantom_run(
    make_logger,
    history_db,
) -> None:
    logger = make_logger(history_db=history_db)
    active = logger.registry.get("active")
    assert active is not None
    active.frames_total = 5

    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(
            logger, logger=logging.getLogger(__name__), sleep=_raise_stop_loop
        )

    status = logger.status()
    assert status.enabled is False
    assert status.run_id is None
    assert history_db.list_runs() == []


@pytest.mark.asyncio
async def test_runtime_auto_stops_a_run_at_the_thirty_minute_limit(
    make_logger,
    history_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = make_logger(history_db=history_db)
    monkeypatch.setattr(logger.post_analysis, "schedule", lambda _run_id: None)
    started = logger.start_recording()
    snapshot = logger._lifecycle.snapshot()
    assert snapshot is not None
    logger._sample_flush._monotonic = lambda: snapshot.start_mono_s + 30 * 60 + 1.0

    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(
            logger, logger=logging.getLogger(__name__), sleep=_raise_stop_loop
        )

    status = logger.status()
    assert started.enabled is True
    assert status.enabled is False
    assert status.last_stop_reason == "max_duration"


class _VirtualClock:
    """A monotonic clock that only the loop's sleeps and the ticks' work advance."""

    def __init__(self, *, stop_at_s: float) -> None:
        self.now_s = 0.0
        self.stop_at_s = stop_at_s

    def monotonic(self) -> float:
        return self.now_s

    async def sleep(self, seconds: float) -> None:
        assert seconds >= 0.0
        self.now_s += seconds
        if self.now_s >= self.stop_at_s:
            raise _StopLoop


async def _tick_starts(clock: _VirtualClock, work_s: list[float]) -> list[float]:
    """When each idle tick of a 4 Hz loop started; tick *i*'s work takes ``work_s[i]``."""
    starts: list[float] = []

    def flush_tick() -> tuple[None, None]:
        starts.append(clock.now_s)
        clock.now_s += work_s[min(len(starts), len(work_s)) - 1]
        return None, None

    recorder = SimpleNamespace(
        metrics_log_hz=4,
        flush_tick=flush_tick,
        _persistence=SimpleNamespace(last_write_error=None),
    )
    with pytest.raises(_StopLoop):
        await _recorder_runtime.run_loop(
            recorder,  # type: ignore[arg-type]
            logger=logging.getLogger(__name__),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    return starts


@pytest.mark.asyncio
async def test_ticks_keep_the_configured_rate_whatever_their_own_work_takes() -> None:
    # Sleeping a whole interval after 20 ms of work ticked at 3.7 Hz, not 4 Hz.
    starts = await _tick_starts(_VirtualClock(stop_at_s=60.0), [0.02])

    assert len(starts) == 240
    assert starts[1:] == pytest.approx([0.25 * n for n in range(1, 240)])


@pytest.mark.asyncio
async def test_an_overrunning_tick_resyncs_instead_of_bursting() -> None:
    # Tick 2 runs 0.3 s (past the next deadline, by under an interval); tick 5 runs 1 s.
    work = [0.02, 0.3, 0.02, 0.02, 1.0, 0.02]
    starts = await _tick_starts(_VirtualClock(stop_at_s=3.0), work)

    # A short overrun keeps the deadlines: the late tick runs at once, then on time.
    assert starts[:5] == pytest.approx([0.0, 0.25, 0.55, 0.75, 1.0])
    # A long one starts afresh from its end: no catching up on the ticks it missed.
    assert starts[5:] == pytest.approx([2.0, 2.25, 2.5, 2.75])


def test_next_tick_deadline() -> None:
    deadline = _recorder_runtime.next_tick_deadline
    assert deadline(10.0, 0.25, 10.02) == 10.25
    assert deadline(10.0, 0.25, 10.4) == 10.25
    assert deadline(10.0, 0.25, 10.5) == 10.25
    assert deadline(10.0, 0.25, 10.6) == 10.6
