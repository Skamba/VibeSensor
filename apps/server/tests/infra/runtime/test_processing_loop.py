"""Behavioral tests for ProcessingLoop – failure counting, backoff, and mismatch detection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from vibesensor.infra.runtime.processing_failure_policy import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_FATAL_BACKOFF_CYCLES,
)
from vibesensor.infra.runtime.processing_failures import (
    ProcessingFailureCategory,
    ProcessingTickFailure,
)
from vibesensor.infra.runtime.processing_loop import ProcessingLoop
from vibesensor.infra.runtime.processing_state import ProcessingHealth, ProcessingLoopState
from vibesensor.infra.runtime.processing_tick import ProcessingTickRunner
from vibesensor.shared.exceptions import ProcessingError
from vibesensor.shared.runtime_failures import ProcessingLoopFailure

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _StubRecord:
    sample_rate_hz: int = 800
    frame_samples: int = 1024


class _StubRegistry:
    def __init__(self, clients: dict | None = None) -> None:
        self._clients: dict[str, _StubRecord] = clients or {}

    def evict_stale(self) -> None:
        pass

    def active_client_ids(self) -> list[str]:
        return list(self._clients.keys())

    def get(self, client_id: str) -> _StubRecord | None:
        return self._clients.get(client_id)


class _StubProcessor:
    def __init__(self, *, fail_count: int = 0) -> None:
        self._fail_count = fail_count
        self._call_count = 0
        self.compute_all_calls = 0
        self.compute_call_args: list[tuple[list[str], dict[str, int]]] = []
        self.evict_calls: list[set[str]] = []

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        self._call_count += 1
        self.compute_all_calls += 1
        self.compute_call_args.append((list(client_ids), dict(sample_rates_hz or {})))
        if self._call_count <= self._fail_count:
            raise ProcessingError("stub compute_all failure")
        return {}

    def evict_clients(self, active: set[str]) -> None:
        self.evict_calls.append(set(active))


class _StubControlPlane:
    def __init__(self) -> None:
        self.broadcast_calls = 0

    def broadcast_sync_clock(self) -> int:
        self.broadcast_calls += 1
        return 1


def _make_loop(
    *,
    processor: Any = None,
    registry: Any = None,
    sample_rate_hz: int = 800,
    fft_n: int = 2048,
    fft_update_hz: int = 10,
    control_plane: Any = None,
) -> tuple[ProcessingLoop, ProcessingLoopState]:
    state = ProcessingLoopState()
    proc = processor if processor is not None else _StubProcessor()
    reg = registry if registry is not None else _StubRegistry()
    loop = ProcessingLoop(
        state=state,
        fft_update_hz=fft_update_hz,
        sample_rate_hz=sample_rate_hz,
        fft_n=fft_n,
        registry=reg,
        processor=proc,
        control_plane=control_plane,
    )
    return loop, state


def _make_tick_runner(
    *,
    processor: Any = None,
    registry: Any = None,
    sample_rate_hz: int = 800,
    fft_n: int = 2048,
    control_plane: Any = None,
) -> tuple[ProcessingTickRunner, ProcessingLoopState]:
    state = ProcessingLoopState()
    proc = processor if processor is not None else _StubProcessor()
    reg = registry if registry is not None else _StubRegistry()
    runner = ProcessingTickRunner(
        state=state,
        sample_rate_hz=sample_rate_hz,
        fft_n=fft_n,
        registry=reg,
        processor=proc,
        control_plane=control_plane,
    )
    return runner, state


# ---------------------------------------------------------------------------
# Run helper for one-loop public-behavior tests
# ---------------------------------------------------------------------------


async def _run_loop(loop: ProcessingLoop, *, max_ticks: int) -> None:
    """Run *loop.run()* for *max_ticks* sleep calls, then raise CancelledError."""
    tick_count = 0
    original_sleep = asyncio.sleep

    async def _counting_sleep(delay: float) -> None:
        nonlocal tick_count
        tick_count += 1
        if tick_count >= max_ticks:
            raise asyncio.CancelledError
        await original_sleep(0)

    with patch("anyio.sleep", _counting_sleep):
        with pytest.raises(asyncio.CancelledError):
            await loop.run()


async def _capture_first_delay(
    loop: ProcessingLoop,
    *,
    monotonic_points: tuple[float, float],
) -> float:
    captured_delays: list[float] = []
    monotonic_values = iter(monotonic_points)
    final_value = monotonic_points[-1]

    async def _recording_sleep(delay: float) -> None:
        captured_delays.append(delay)
        raise asyncio.CancelledError

    def _fake_monotonic() -> float:
        return next(monotonic_values, final_value)

    with patch(
        "vibesensor.infra.runtime.processing_loop.time.monotonic",
        side_effect=_fake_monotonic,
    ):
        with patch("vibesensor.infra.runtime.processing_loop.anyio.sleep", _recording_sleep):
            with pytest.raises(asyncio.CancelledError):
                await loop.run()

    assert captured_delays
    return captured_delays[0]


# ---------------------------------------------------------------------------
# Failure tracking and backoff tests
# ---------------------------------------------------------------------------


class TestProcessingLoopFailureTracking:
    """Cover failure accounting, fatal backoff, and recovery transitions in the loop state."""

    @pytest.mark.asyncio
    async def test_single_failure_records_category_and_count(self) -> None:
        """A single processing tick failure records category and increments failure count."""
        processor = _StubProcessor(fail_count=1)
        loop, state = _make_loop(processor=processor)

        await _run_loop(loop, max_ticks=1)

        assert state.processing_failure_count == 1
        assert state.last_failure_category == "compute_all"
        assert state.processing_state == ProcessingHealth.DEGRADED

    @pytest.mark.asyncio
    async def test_fatal_backoff_triggers_at_max_consecutive_failures(self) -> None:
        """After MAX_CONSECUTIVE_FAILURES failures the state transitions to FATAL."""
        processor = _StubProcessor(fail_count=MAX_CONSECUTIVE_FAILURES + 10)
        loop, state = _make_loop(processor=processor)

        # tick_count=MAX_CONSECUTIVE_FAILURES fires at the fatal backoff sleep
        await _run_loop(loop, max_ticks=MAX_CONSECUTIVE_FAILURES)

        assert state.processing_state == ProcessingHealth.FATAL
        assert state.processing_failure_count == MAX_CONSECUTIVE_FAILURES
        assert state.processing_failure_categories.get("compute_all", 0) == MAX_CONSECUTIVE_FAILURES

    @pytest.mark.asyncio
    async def test_recovery_to_ok_after_backoff(self) -> None:
        """State resets to OK after backoff sleep completes and a successful tick runs."""
        # 25 failures → backoff sleep (ticks 1-24 = delay sleeps, tick 25 = backoff sleep)
        # backoff sleep completes → consecutive_failures = 0, state = DEGRADED
        # tick 26 = delay sleep after failure 25's iteration end
        # iteration 26 = success → state = OK
        # tick 27 fires at delay sleep of success tick → CancelledError
        processor = _StubProcessor(fail_count=MAX_CONSECUTIVE_FAILURES)
        loop, state = _make_loop(processor=processor)

        await _run_loop(loop, max_ticks=MAX_CONSECUTIVE_FAILURES + 2)

        assert state.processing_state == ProcessingHealth.OK
        assert state.tick_count == 1
        assert state.last_failure_category == "compute_all"

    @pytest.mark.asyncio
    async def test_persistent_failures_escalate_after_fatal_backoff_cycles(self) -> None:
        processor = _StubProcessor(
            fail_count=(MAX_CONSECUTIVE_FAILURES * MAX_FATAL_BACKOFF_CYCLES) + 5,
        )
        loop, state = _make_loop(processor=processor)
        original_sleep = asyncio.sleep

        async def _fast_sleep(delay: float) -> None:
            await original_sleep(0)

        with patch("anyio.sleep", _fast_sleep):
            with pytest.raises(ProcessingLoopFailure, match="Processing loop remained unhealthy"):
                await loop.run()

        assert state.processing_state == ProcessingHealth.FATAL

    @pytest.mark.asyncio
    async def test_programmer_bug_propagates_from_ingress_state(self) -> None:
        """Unexpected runtime bugs in ingress state should now fail explicitly."""
        mock_proc = MagicMock()
        mock_proc.clients_with_recent_data.return_value = []
        mock_proc.evict_clients.return_value = None
        mock_registry = MagicMock()
        mock_registry.active_client_ids.side_effect = RuntimeError("unexpected boom")
        loop, state = _make_loop(processor=mock_proc, registry=mock_registry)

        with pytest.raises(RuntimeError, match="unexpected boom"):
            await _run_loop(loop, max_ticks=1)

        assert state.processing_failure_count == 0

    @pytest.mark.asyncio
    async def test_failure_message_is_truncated_at_limit(self) -> None:
        """Long exception messages are truncated to _MAX_FAILURE_MESSAGE_LEN."""
        long_msg = "x" * 300
        mock_proc = MagicMock()
        mock_proc.clients_with_recent_data.return_value = []
        mock_proc.compute_all.side_effect = ProcessingError(long_msg)
        mock_proc.evict_clients.return_value = None
        mock_registry = MagicMock()
        mock_registry.active_client_ids.return_value = []
        loop, state = _make_loop(processor=mock_proc, registry=mock_registry)

        await _run_loop(loop, max_ticks=1)

        assert state.last_failure_message is not None
        assert len(state.last_failure_message) <= 242  # 239 chars + "..."


# ---------------------------------------------------------------------------
# Tick-runner mismatch detection and public loop cadence tests
# ---------------------------------------------------------------------------


class TestProcessingLoopMismatchDetection:
    """Verify sync-clock handling and mismatch tracking without loop private methods."""

    @pytest.mark.asyncio
    async def test_sync_clock_uses_control_plane_broadcaster(self) -> None:
        """Sync-clock ticks use the public ProcessingTickRunner seam."""
        processor = _StubProcessor()
        control_plane = _StubControlPlane()
        runner, _state = _make_tick_runner(
            processor=processor,
            control_plane=control_plane,
        )

        await runner.run(sync_clock=True)

        assert control_plane.broadcast_calls == 1


class TestProcessingLoopCadence:
    @pytest.mark.asyncio
    async def test_success_delay_uses_low_load_fast_path_with_duty_cap(self) -> None:
        clients = {f"sensor-{index}": _StubRecord() for index in range(5)}
        loop, _state = _make_loop(
            registry=_StubRegistry(clients),
            fft_update_hz=4,
        )

        delay_s = await _capture_first_delay(
            loop,
            monotonic_points=(0.0, 0.04),
        )

        assert delay_s == pytest.approx(0.06)

    @pytest.mark.asyncio
    async def test_success_delay_keeps_base_interval_for_larger_active_set(self) -> None:
        clients = {f"sensor-{index}": _StubRecord() for index in range(12)}
        loop, _state = _make_loop(
            registry=_StubRegistry(clients),
            fft_update_hz=4,
        )

        delay_s = await _capture_first_delay(
            loop,
            monotonic_points=(0.0, 0.04),
        )

        assert delay_s == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_success_delay_keeps_base_interval_when_idle(self) -> None:
        loop, _state = _make_loop(fft_update_hz=4)

        delay_s = await _capture_first_delay(
            loop,
            monotonic_points=(0.0, 0.01),
        )

        assert delay_s == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_sync_clock_offloads_broadcast_to_thread(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        processor = _StubProcessor()
        control_plane = _StubControlPlane()
        runner, _state = _make_tick_runner(
            processor=processor,
            control_plane=control_plane,
        )
        to_thread_calls: list[tuple[object | None, str]] = []

        async def fake_to_thread(func, /, *args, **kwargs):
            to_thread_calls.append(
                (
                    getattr(func, "__self__", None),
                    getattr(func, "__name__", type(func).__name__),
                ),
            )
            return func(*args, **kwargs)

        monkeypatch.setattr(
            "vibesensor.infra.runtime.processing_tick.anyio.to_thread.run_sync",
            fake_to_thread,
        )

        await runner.run(sync_clock=True)

        assert to_thread_calls[0] == (control_plane, "broadcast_sync_clock")
        assert control_plane.broadcast_calls == 1

    @pytest.mark.asyncio
    async def test_sample_rate_mismatch_logged_once(self) -> None:
        """Sample-rate mismatch for a client is recorded in state exactly once."""
        mismatched = _StubRecord(sample_rate_hz=400, frame_samples=1024)
        registry = _StubRegistry(clients={"sess_a": mismatched})
        processor = _StubProcessor()
        runner, state = _make_tick_runner(
            processor=processor,
            registry=registry,
            sample_rate_hz=800,
        )

        await runner.run(sync_clock=False)
        await runner.run(sync_clock=False)

        assert "sess_a" in state.sample_rate_mismatch_logged
        assert len(state.sample_rate_mismatch_logged) == 1

    @pytest.mark.asyncio
    async def test_matching_sample_rate_not_logged(self) -> None:
        """Clients whose sample_rate_hz matches the config are not flagged."""
        matching = _StubRecord(sample_rate_hz=800, frame_samples=1024)
        registry = _StubRegistry(clients={"sess_b": matching})
        processor = _StubProcessor()
        runner, state = _make_tick_runner(
            processor=processor,
            registry=registry,
            sample_rate_hz=800,
        )

        await runner.run(sync_clock=False)

        assert len(state.sample_rate_mismatch_logged) == 0

    @pytest.mark.asyncio
    async def test_frame_size_mismatch_logged_once(self) -> None:
        """Frame-size larger than fft_n is recorded in state exactly once."""
        oversized = _StubRecord(sample_rate_hz=800, frame_samples=4096)
        registry = _StubRegistry(clients={"sess_c": oversized})
        processor = _StubProcessor()
        runner, state = _make_tick_runner(
            processor=processor,
            registry=registry,
            fft_n=2048,
        )

        await runner.run(sync_clock=False)
        await runner.run(sync_clock=False)

        assert "sess_c" in state.frame_size_mismatch_logged
        assert len(state.frame_size_mismatch_logged) == 1

    @pytest.mark.asyncio
    async def test_frame_size_within_fft_n_not_logged(self) -> None:
        """Frame-size at or below fft_n is not flagged."""
        fine = _StubRecord(sample_rate_hz=800, frame_samples=2048)
        registry = _StubRegistry(clients={"sess_d": fine})
        processor = _StubProcessor()
        runner, state = _make_tick_runner(
            processor=processor,
            registry=registry,
            fft_n=2048,
        )

        await runner.run(sync_clock=False)

        assert len(state.frame_size_mismatch_logged) == 0


class TestProcessingLoopCleanup:
    """Ensure eviction cleanup still runs around compute failures and disappearing clients."""

    @pytest.mark.asyncio
    async def test_compute_all_failure_still_evicts_using_fresh_active_ids(self) -> None:
        class _RefreshingRegistry(_StubRegistry):
            def __init__(self) -> None:
                super().__init__(
                    clients={
                        "stay": _StubRecord(sample_rate_hz=800, frame_samples=512),
                        "drop": _StubRecord(sample_rate_hz=800, frame_samples=512),
                    }
                )
                self._active_snapshots = [
                    ["stay", "drop"],
                    ["stay"],
                ]

            def active_client_ids(self) -> list[str]:
                if self._active_snapshots:
                    return self._active_snapshots.pop(0)
                return ["stay"]

        registry = _RefreshingRegistry()
        processor = _StubProcessor(fail_count=1)
        runner, _state = _make_tick_runner(
            processor=processor,
            registry=registry,
        )

        with pytest.raises(ProcessingTickFailure, match="stub compute_all failure") as exc_info:
            await runner.run(sync_clock=False)

        assert exc_info.value.category is ProcessingFailureCategory.COMPUTE_ALL
        assert processor.compute_call_args == [
            (
                ["stay", "drop"],
                {"stay": 800, "drop": 800},
            )
        ]
        assert processor.evict_calls == [{"stay"}]

    @pytest.mark.asyncio
    async def test_disappeared_client_is_skipped_before_compute_all(self) -> None:
        class _DisappearingRegistry(_StubRegistry):
            def __init__(self) -> None:
                super().__init__(
                    clients={
                        "stay": _StubRecord(sample_rate_hz=800, frame_samples=512),
                        "gone": _StubRecord(sample_rate_hz=400, frame_samples=256),
                    }
                )

            def get(self, client_id: str) -> _StubRecord | None:
                if client_id == "gone":
                    return None
                return super().get(client_id)

        registry = _DisappearingRegistry()
        processor = _StubProcessor()
        runner, _state = _make_tick_runner(
            processor=processor,
            registry=registry,
        )

        await runner.run(sync_clock=False)

        assert processor.compute_call_args == [
            (
                ["stay"],
                {"stay": 800},
            )
        ]
        assert processor.evict_calls == [{"stay", "gone"}]
