"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from vibesensor.esp_flash_manager import EspFlashManager
from vibesensor.report import pdf_diagram
from vibesensor.ws_hub import WebSocketHub

_PDF_DIAGRAM_SRC = inspect.getsource(pdf_diagram)

_RUN_FLASH_JOB_SRC = inspect.getsource(EspFlashManager._run_flash_job)

_I18N_ERROR_KEYS = [
    "settings.car.delete_failed",
    "settings.car.activate_failed",
    "settings.car.save_failed",
]


class TestWebSocketHubCircuitBreaker:
    """Verify consecutive failure tracking in ws_hub.run()."""

    _WS_HUB_RUN_SRC = inspect.getsource(WebSocketHub.run)

    def test_run_method_has_consecutive_failure_tracking(self):
        """ws_hub.run() should track consecutive failures."""
        assert "_consecutive_failures" in self._WS_HUB_RUN_SRC, (
            "run() should track consecutive failures"
        )
        assert "_MAX_CONSECUTIVE_FAILURES" in self._WS_HUB_RUN_SRC, (
            "run() should have a max consecutive failures threshold"
        )

    def test_failure_counter_resets_on_success(self):
        """After a successful tick, the failure counter should reset."""
        assert "_consecutive_failures = 0" in self._WS_HUB_RUN_SRC, (
            "Failure counter should be reset to 0 on success"
        )

    @pytest.mark.asyncio
    async def test_run_tolerates_failures_and_continues(self):
        """run() should not crash on on_tick exceptions; it keeps retrying."""
        hub = WebSocketHub()
        call_count = 0

        def failing_tick():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise RuntimeError("tick fail")

        def dummy_builder(sel_id=None):
            return {}

        async def stop_after_4():
            """Let the loop run enough ticks, then cancel."""
            while call_count < 4:
                await asyncio.sleep(0.005)

        task = asyncio.create_task(
            hub.run(hz=200, payload_builder=dummy_builder, on_tick=failing_tick)
        )
        try:
            await asyncio.wait_for(stop_after_4(), timeout=5.0)
        except TimeoutError:
            pass
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert call_count >= 4, (
            f"on_tick should have been called at least 4 times, got {call_count}"
        )
