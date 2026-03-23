"""Behavioral tests for ProcessingLoop – failure counting, backoff, and mismatch detection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from vibesensor.infra.runtime.processing_loop import (
    MAX_CONSECUTIVE_FAILURES,
    MAX_FATAL_BACKOFF_CYCLES,
    ProcessingHealth,
    ProcessingLoop,
    ProcessingLoopState,
)

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

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        self._call_count += 1
        self.compute_all_calls += 1
        if self._call_count <= self._fail_count:
            raise RuntimeError("stub compute_all failure")
        return {}

    def evict_clients(self, active: set[str]) -> None:
        pass


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
    control_plane: Any = None,
) -> tuple[ProcessingLoop, ProcessingLoopState]:
    state = ProcessingLoopState()
    proc = processor if processor is not None else _StubProcessor()
    reg = registry if registry is not None else _StubRegistry()
    loop = ProcessingLoop(
        state=state,
        fft_update_hz=10,
        sample_rate_hz=sample_rate_hz,
        fft_n=fft_n,
        registry=reg,
        processor=proc,
        control_plane=control_plane,
    )
    return loop, state


# ---------------------------------------------------------------------------
# Run helper (mirrors test_runtime.py pattern)
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

    with patch("asyncio.sleep", _counting_sleep):
        with pytest.raises(asyncio.CancelledError):
            await loop.run()


# ---------------------------------------------------------------------------
# Failure tracking and backoff tests
# ---------------------------------------------------------------------------


class TestProcessingLoopFailureTracking:
    @pytest.mark.asyncio
    async def test_single_failure_records_category_and_count(self) -> None:
        """A single ProcessingLoopError records category and increments failure count."""
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
        assert state.fatal_backoff_cycles == 0
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

        with patch("asyncio.sleep", _fast_sleep):
            with pytest.raises(RuntimeError, match="persistent processing failure"):
                await loop.run()

        assert state.processing_state == ProcessingHealth.FATAL
        assert state.fatal_backoff_cycles == MAX_FATAL_BACKOFF_CYCLES

    @pytest.mark.asyncio
    async def test_uncategorized_exception_falls_into_unexpected(self) -> None:
        """A non-ProcessingLoopError Exception is categorized as 'unexpected'."""
        mock_proc = MagicMock()
        mock_proc.clients_with_recent_data.return_value = []
        mock_proc.evict_clients.return_value = None
        # Raise from a method before compute_all wraps it (use evict_stale path via registry)
        mock_registry = MagicMock()
        mock_registry.active_client_ids.side_effect = RuntimeError("unexpected boom")
        loop, state = _make_loop(processor=mock_proc, registry=mock_registry)

        await _run_loop(loop, max_ticks=1)

        assert state.processing_failure_count == 1
        assert "ingress_state" in state.processing_failure_categories

    @pytest.mark.asyncio
    async def test_failure_message_is_truncated_at_limit(self) -> None:
        """Long exception messages are truncated to _MAX_FAILURE_MESSAGE_LEN."""
        long_msg = "x" * 300
        mock_proc = MagicMock()
        mock_proc.clients_with_recent_data.return_value = []
        mock_proc.evict_clients.return_value = None
        mock_registry = MagicMock()
        mock_registry.active_client_ids.side_effect = RuntimeError(long_msg)
        loop, state = _make_loop(processor=mock_proc, registry=mock_registry)

        await _run_loop(loop, max_ticks=1)

        assert state.last_failure_message is not None
        assert len(state.last_failure_message) <= 242  # 239 chars + "..."


# ---------------------------------------------------------------------------
# Mismatch detection tests (via _run_tick directly)
# ---------------------------------------------------------------------------


class TestProcessingLoopMismatchDetection:
    @pytest.mark.asyncio
    async def test_sync_clock_uses_control_plane_broadcaster(self) -> None:
        """Sync-clock ticks use the injected control-plane broadcaster seam."""
        processor = _StubProcessor()
        control_plane = _StubControlPlane()
        loop, _state = _make_loop(processor=processor, control_plane=control_plane)

        await loop._run_tick(sync_clock=True)

        assert control_plane.broadcast_calls == 1

    @pytest.mark.asyncio
    async def test_sample_rate_mismatch_logged_once(self) -> None:
        """Sample-rate mismatch for a client is recorded in state exactly once."""
        mismatched = _StubRecord(sample_rate_hz=400, frame_samples=1024)
        registry = _StubRegistry(clients={"sess_a": mismatched})
        processor = _StubProcessor()
        loop, state = _make_loop(processor=processor, registry=registry, sample_rate_hz=800)

        # Call _run_tick twice; mismatch should be logged only once.
        await loop._run_tick(sync_clock=False)
        await loop._run_tick(sync_clock=False)

        assert "sess_a" in state.sample_rate_mismatch_logged
        assert len(state.sample_rate_mismatch_logged) == 1

    @pytest.mark.asyncio
    async def test_matching_sample_rate_not_logged(self) -> None:
        """Clients whose sample_rate_hz matches the config are not flagged."""
        matching = _StubRecord(sample_rate_hz=800, frame_samples=1024)
        registry = _StubRegistry(clients={"sess_b": matching})
        processor = _StubProcessor()
        loop, state = _make_loop(processor=processor, registry=registry, sample_rate_hz=800)

        await loop._run_tick(sync_clock=False)

        assert len(state.sample_rate_mismatch_logged) == 0

    @pytest.mark.asyncio
    async def test_frame_size_mismatch_logged_once(self) -> None:
        """Frame-size larger than fft_n is recorded in state exactly once."""
        oversized = _StubRecord(sample_rate_hz=800, frame_samples=4096)
        registry = _StubRegistry(clients={"sess_c": oversized})
        processor = _StubProcessor()
        loop, state = _make_loop(processor=processor, registry=registry, fft_n=2048)

        await loop._run_tick(sync_clock=False)
        await loop._run_tick(sync_clock=False)

        assert "sess_c" in state.frame_size_mismatch_logged
        assert len(state.frame_size_mismatch_logged) == 1

    @pytest.mark.asyncio
    async def test_frame_size_within_fft_n_not_logged(self) -> None:
        """Frame-size at or below fft_n is not flagged."""
        fine = _StubRecord(sample_rate_hz=800, frame_samples=2048)
        registry = _StubRegistry(clients={"sess_d": fine})
        processor = _StubProcessor()
        loop, state = _make_loop(processor=processor, registry=registry, fft_n=2048)

        await loop._run_tick(sync_clock=False)

        assert len(state.frame_size_mismatch_logged) == 0
