# ruff: noqa: E501
"""Tests for Cycle 9 fixes: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ── 1. EspFlashManager CancelledError ────────────────────────────────────


class TestEspFlashManagerCancelledError:
    """Verify CancelledError is caught, status finalized, and re-raised."""

    def test_cancelled_error_handler_exists(self):
        """The except block for CancelledError must precede except Exception."""
        import inspect

        from vibesensor.esp_flash_manager import EspFlashManager

        source = inspect.getsource(EspFlashManager._run_flash_job)
        cancel_pos = source.find("except asyncio.CancelledError")
        generic_pos = source.find("except Exception")
        assert cancel_pos != -1, "CancelledError handler not found in _run_flash_job"
        assert cancel_pos < generic_pos, (
            "CancelledError handler must appear before generic Exception handler"
        )

    def test_cancelled_error_re_raises(self):
        """The CancelledError handler must re-raise."""
        import inspect

        from vibesensor.esp_flash_manager import EspFlashManager

        source = inspect.getsource(EspFlashManager._run_flash_job)
        # Find the CancelledError block and check it has 'raise' after it
        cancel_block_start = source.find("except asyncio.CancelledError")
        generic_block_start = source.find("except Exception")
        cancel_block = source[cancel_block_start:generic_block_start]
        assert "raise" in cancel_block, (
            "CancelledError handler must re-raise the exception"
        )


# ── 2. PDF diagram SOURCE_LEGEND_TITLE dead fallback ─────────────────────


class TestPdfDiagramDeadFallback:
    """Verify the dead English fallback for SOURCE_LEGEND_TITLE was removed."""

    def test_no_inline_english_fallback(self):
        """pdf_diagram.py should not contain 'Finding source:' as a fallback."""
        import inspect

        from vibesensor.report import pdf_diagram

        source = inspect.getsource(pdf_diagram)
        assert 'else "Finding source:"' not in source, (
            "Dead English fallback 'Finding source:' should be removed"
        )

    def test_tr_called_directly(self):
        """tr('SOURCE_LEGEND_TITLE') should be called without a conditional guard."""
        import inspect

        from vibesensor.report import pdf_diagram

        source = inspect.getsource(pdf_diagram)
        assert 'tr("SOURCE_LEGEND_TITLE")' in source, (
            "tr('SOURCE_LEGEND_TITLE') should remain as a direct call"
        )
        # The old pattern was: tr("SOURCE_LEGEND_TITLE") if tr("SOURCE_LEGEND_TITLE") != "SOURCE_LEGEND_TITLE"
        assert source.count('tr("SOURCE_LEGEND_TITLE")') < 3, (
            "Should not have the old double-invocation conditional pattern"
        )


# ── 3. PDF diagram bare assert → ValueError ─────────────────────────────


class TestPdfDiagramAssertReplacement:
    """Verify bare assert replaced with ValueError for label placement."""

    def test_no_bare_assert_best(self):
        """pdf_diagram.py should not use bare assert for best placement."""
        import inspect

        from vibesensor.report import pdf_diagram

        source = inspect.getsource(pdf_diagram)
        assert "assert best is not None" not in source, (
            "Bare 'assert best is not None' should be replaced with ValueError"
        )

    def test_value_error_on_no_placement(self):
        """When no label placement is found, ValueError should be raised."""
        import inspect

        from vibesensor.report import pdf_diagram

        source = inspect.getsource(pdf_diagram)
        assert "raise ValueError" in source, (
            "Should raise ValueError when no valid label placement is found"
        )


# ── 4. Dead _owns_pool flag removed from SignalProcessor ─────────────────


class TestOwnsPoolRemoval:
    """Verify _owns_pool dead code was removed from SignalProcessor."""

    def test_no_owns_pool_attribute(self):
        """SignalProcessor should not have _owns_pool attribute."""
        import inspect

        from vibesensor.processing import SignalProcessor

        source = inspect.getsource(SignalProcessor.__init__)
        assert "_owns_pool" not in source, (
            "Dead _owns_pool flag should be removed from SignalProcessor.__init__"
        )

    def test_constructor_still_works(self):
        """SignalProcessor can still be constructed with or without a pool."""
        from vibesensor.processing import SignalProcessor

        proc = SignalProcessor(
            sample_rate_hz=200,
            waveform_seconds=5,
            waveform_display_hz=30,
            fft_n=256,
        )
        assert not hasattr(proc, "_owns_pool"), (
            "_owns_pool attribute should not exist on SignalProcessor instances"
        )


# ── 5. report_cli.py error handling ──────────────────────────────────────


class TestReportCliErrorHandling:
    """Verify report_cli.main() handles missing/corrupt input gracefully."""

    def test_missing_file_returns_1(self, capsys):
        """main() returns 1 with friendly message for missing input."""
        from vibesensor.report_cli import main

        with patch("sys.argv", ["report_cli", "/nonexistent/path.jsonl"]):
            rc = main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower() or "error" in captured.err.lower()

    def test_corrupt_json_returns_1(self, tmp_path, capsys):
        """main() returns 1 with friendly message for corrupt JSON."""
        bad_file = tmp_path / "corrupt.jsonl"
        bad_file.write_text("{invalid json\n", encoding="utf-8")
        from vibesensor.report_cli import main

        with patch("sys.argv", ["report_cli", str(bad_file)]):
            rc = main()
        assert rc == 1
        captured = capsys.readouterr()
        assert "error" in captured.err.lower()


# ── 6. WebSocketHub circuit breaker ──────────────────────────────────────


class TestWebSocketHubCircuitBreaker:
    """Verify consecutive failure tracking in ws_hub.run()."""

    def test_run_method_has_consecutive_failure_tracking(self):
        """ws_hub.run() should track consecutive failures."""
        import inspect

        from vibesensor.ws_hub import WebSocketHub

        source = inspect.getsource(WebSocketHub.run)
        assert "_consecutive_failures" in source, (
            "run() should track consecutive failures"
        )
        assert "_MAX_CONSECUTIVE_FAILURES" in source, (
            "run() should have a max consecutive failures threshold"
        )

    def test_failure_counter_resets_on_success(self):
        """After a successful tick, the failure counter should reset."""
        import inspect

        from vibesensor.ws_hub import WebSocketHub

        source = inspect.getsource(WebSocketHub.run)
        # The counter should be reset to 0 after a successful broadcast
        assert "_consecutive_failures = 0" in source, (
            "Failure counter should be reset to 0 on success"
        )

    @pytest.mark.asyncio
    async def test_run_tolerates_failures_and_continues(self):
        """run() should not crash on on_tick exceptions; it keeps retrying."""
        from vibesensor.ws_hub import WebSocketHub

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
        except asyncio.TimeoutError:
            pass
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert call_count >= 4, f"on_tick should have been called at least 4 times, got {call_count}"


# ── 7. CSV export record_type/schema_version population ──────────────────


class TestCsvExportFieldPopulation:
    """Verify _flatten_for_csv populates record_type and schema_version."""

    def test_empty_row_gets_defaults(self):
        """A row with no record_type/schema_version gets them populated."""
        from vibesensor.api import _flatten_for_csv

        result = _flatten_for_csv({"accel_x_g": 0.5, "t_s": 1.0})
        assert result["record_type"] == "sample"
        assert result["schema_version"] == "2"

    def test_existing_values_preserved(self):
        """If record_type/schema_version are already in the row, keep them."""
        from vibesensor.api import _flatten_for_csv

        result = _flatten_for_csv({"record_type": "meta", "schema_version": "3"})
        assert result["record_type"] == "meta"
        assert result["schema_version"] == "3"

    def test_extras_still_work(self):
        """Non-column keys are still collected into extras."""
        from vibesensor.api import _flatten_for_csv

        result = _flatten_for_csv({"accel_x_g": 0.5, "custom_field": "hello"})
        assert result["record_type"] == "sample"
        assert "extras" in result
        extras = json.loads(result["extras"])
        assert extras["custom_field"] == "hello"

    def test_list_values_json_serialized(self):
        """List/dict values in known columns are JSON-serialized."""
        from vibesensor.api import _flatten_for_csv

        result = _flatten_for_csv({"top_peaks": [1, 2, 3]})
        assert result["top_peaks"] == "[1, 2, 3]"
        assert result["record_type"] == "sample"


# ── 8. i18n keys for car error feedback ──────────────────────────────────


class TestCarErrorI18nKeys:
    """Verify i18n keys for car error feedback exist in both catalogs."""

    @pytest.mark.parametrize(
        "key",
        [
            "settings.car.delete_failed",
            "settings.car.activate_failed",
            "settings.car.save_failed",
        ],
    )
    def test_en_key_exists(self, key):
        en_path = Path(__file__).resolve().parent.parent / "vibesensor" / ".." / ".." / "ui" / "src" / "i18n" / "catalogs" / "en.json"
        # Use the known workspace layout
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        en_path = repo_root / "apps" / "ui" / "src" / "i18n" / "catalogs" / "en.json"
        catalog = json.loads(en_path.read_text(encoding="utf-8"))
        assert key in catalog, f"Missing i18n key {key!r} in en.json"

    @pytest.mark.parametrize(
        "key",
        [
            "settings.car.delete_failed",
            "settings.car.activate_failed",
            "settings.car.save_failed",
        ],
    )
    def test_nl_key_exists(self, key):
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        nl_path = repo_root / "apps" / "ui" / "src" / "i18n" / "catalogs" / "nl.json"
        catalog = json.loads(nl_path.read_text(encoding="utf-8"))
        assert key in catalog, f"Missing i18n key {key!r} in nl.json"
