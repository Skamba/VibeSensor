# ruff: noqa: E402, E501
from __future__ import annotations

"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
"""


import asyncio
import contextlib
import json
from unittest.mock import patch

import pytest
from _paths import REPO_ROOT

from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.cli.report import main as report_cli_main

_I18N_ERROR_KEYS = [
    "settings.car.delete_failed",
    "settings.car.activate_failed",
    "settings.car.save_failed",
]

# ── 5. report_cli.py error handling ──────────────────────────────────────


class TestReportCliErrorHandling:
    """Verify report_cli.main() handles missing/corrupt input gracefully."""

    def test_missing_file_returns_1(self, capsys):
        """main() returns 1 with friendly message for missing input."""
        with patch("sys.argv", ["report_cli", "/nonexistent/path.jsonl"]):
            rc = report_cli_main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "error" in captured.err.lower()

    def test_corrupt_json_returns_1(self, tmp_path, capsys):
        """main() returns 1 with friendly message for corrupt JSON."""
        bad_file = tmp_path / "corrupt.jsonl"
        bad_file.write_text("{invalid json\n", encoding="utf-8")

        with patch("sys.argv", ["report_cli", str(bad_file)]):
            rc = report_cli_main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "error" in captured.err.lower()


# ── 6. WebSocketHub circuit breaker ──────────────────────────────────────


class TestWebSocketHubCircuitBreaker:
    """Verify consecutive failure tracking in ws_hub.run()."""

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
            hub.run(hz=200, payload_builder=dummy_builder, on_tick=failing_tick),
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_after_4(), timeout=5.0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert call_count >= 4, (
            f"on_tick should have been called at least 4 times, got {call_count}"
        )


# ── 8. i18n keys for car error feedback ──────────────────────────────────


class TestCarErrorI18nKeys:
    """Verify i18n keys for car error feedback exist in both catalogs."""

    @pytest.mark.parametrize("key", _I18N_ERROR_KEYS)
    @pytest.mark.parametrize("lang", ["en", "nl"])
    def test_i18n_key_exists(self, lang, key):
        catalog_path = REPO_ROOT / "apps" / "ui" / "src" / "i18n" / "catalogs" / f"{lang}.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert key in catalog, f"Missing i18n key {key!r} in {lang}.json"
