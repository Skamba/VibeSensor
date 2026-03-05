# ruff: noqa: E501
"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import patch

import pytest
from _paths import REPO_ROOT

from vibesensor.api import _flatten_for_csv
from vibesensor.esp_flash_manager import EspFlashManager
from vibesensor.processing import SignalProcessor
from vibesensor.report import pdf_diagram
from vibesensor.report_cli import main as report_cli_main
from vibesensor.ws_hub import WebSocketHub

_PDF_DIAGRAM_SRC = inspect.getsource(pdf_diagram)
_RUN_FLASH_JOB_SRC = inspect.getsource(EspFlashManager._run_flash_job)

_I18N_ERROR_KEYS = [
    "settings.car.delete_failed",
    "settings.car.activate_failed",
    "settings.car.save_failed",
]

# ── 1. EspFlashManager CancelledError ────────────────────────────────────


class TestEspFlashManagerCancelledError:
    """Verify CancelledError is caught, status finalized, and re-raised."""

    def test_cancelled_error_handler_exists(self):
        """The except block for CancelledError must precede except Exception."""
        cancel_pos = _RUN_FLASH_JOB_SRC.find("except asyncio.CancelledError")
        generic_pos = _RUN_FLASH_JOB_SRC.find("except Exception")
        assert cancel_pos != -1, "CancelledError handler not found in _run_flash_job"
        assert cancel_pos < generic_pos, (
            "CancelledError handler must appear before generic Exception handler"
        )

    def test_cancelled_error_re_raises(self):
        """The CancelledError handler must re-raise."""
        cancel_block_start = _RUN_FLASH_JOB_SRC.find("except asyncio.CancelledError")
        generic_block_start = _RUN_FLASH_JOB_SRC.find("except Exception")
        cancel_block = _RUN_FLASH_JOB_SRC[cancel_block_start:generic_block_start]
        assert "raise" in cancel_block, "CancelledError handler must re-raise the exception"


# ── 2. PDF diagram SOURCE_LEGEND_TITLE dead fallback ─────────────────────


class TestPdfDiagramDeadFallback:
    """Verify the dead English fallback for SOURCE_LEGEND_TITLE was removed."""

    def test_no_inline_english_fallback(self):
        """pdf_diagram.py should not contain 'Finding source:' as a fallback."""
        assert 'else "Finding source:"' not in _PDF_DIAGRAM_SRC, (
            "Dead English fallback 'Finding source:' should be removed"
        )

    def test_tr_called_directly(self):
        """tr('SOURCE_LEGEND_TITLE') should be called without a conditional guard."""
        assert 'tr("SOURCE_LEGEND_TITLE")' in _PDF_DIAGRAM_SRC, (
            "tr('SOURCE_LEGEND_TITLE') should remain as a direct call"
        )
        # The old pattern was: tr("SOURCE_LEGEND_TITLE") if tr("SOURCE_LEGEND_TITLE") != "SOURCE_LEGEND_TITLE"
        assert _PDF_DIAGRAM_SRC.count('tr("SOURCE_LEGEND_TITLE")') < 3, (
            "Should not have the old double-invocation conditional pattern"
        )


# ── 3. PDF diagram bare assert → ValueError ─────────────────────────────


class TestPdfDiagramAssertReplacement:
    """Verify bare assert replaced with ValueError for label placement."""

    def test_no_bare_assert_best(self):
        """pdf_diagram.py should not use bare assert for best placement."""
        assert "assert best is not None" not in _PDF_DIAGRAM_SRC, (
            "Bare 'assert best is not None' should be replaced with ValueError"
        )

    def test_value_error_on_no_placement(self):
        """When no label placement is found, ValueError should be raised."""
        assert "raise ValueError" in _PDF_DIAGRAM_SRC, (
            "Should raise ValueError when no valid label placement is found"
        )


# ── 4. Dead _owns_pool flag removed from SignalProcessor ─────────────────


class TestOwnsPoolRemoval:
    """Verify _owns_pool dead code was removed from SignalProcessor."""

    def test_no_owns_pool_attribute(self):
        """SignalProcessor should not have _owns_pool attribute."""
        source = inspect.getsource(SignalProcessor.__init__)
        assert "_owns_pool" not in source, (
            "Dead _owns_pool flag should be removed from SignalProcessor.__init__"
        )

    def test_constructor_still_works(self):
        """SignalProcessor can still be constructed with or without a pool."""
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


# ── 7. CSV export record_type/schema_version population ──────────────────


class TestCsvExportFieldPopulation:
    """Verify _flatten_for_csv populates record_type and schema_version."""

    def test_empty_row_gets_defaults(self):
        """A row with no record_type/schema_version gets them populated."""
        result = _flatten_for_csv({"accel_x_g": 0.5, "t_s": 1.0})
        assert result["record_type"] == "sample"
        assert result["schema_version"] == "2"

    def test_existing_values_preserved(self):
        """If record_type/schema_version are already in the row, keep them."""
        result = _flatten_for_csv({"record_type": "meta", "schema_version": "3"})
        assert result["record_type"] == "meta"
        assert result["schema_version"] == "3"

    def test_extras_still_work(self):
        """Non-column keys are still collected into extras."""
        result = _flatten_for_csv({"accel_x_g": 0.5, "custom_field": "hello"})
        assert result["record_type"] == "sample"
        assert "extras" in result
        extras = json.loads(result["extras"])
        assert extras["custom_field"] == "hello"

    def test_list_values_json_serialized(self):
        """List/dict values in known columns are JSON-serialized."""
        result = _flatten_for_csv({"top_peaks": [1, 2, 3]})
        assert result["top_peaks"] == "[1, 2, 3]"
        assert result["record_type"] == "sample"


# ── 8. i18n keys for car error feedback ──────────────────────────────────


class TestCarErrorI18nKeys:
    """Verify i18n keys for car error feedback exist in both catalogs."""

    @pytest.mark.parametrize("key", _I18N_ERROR_KEYS)
    @pytest.mark.parametrize("lang", ["en", "nl"])
    def test_i18n_key_exists(self, lang, key):
        catalog_path = REPO_ROOT / "apps" / "ui" / "src" / "i18n" / "catalogs" / f"{lang}.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert key in catalog, f"Missing i18n key {key!r} in {lang}.json"
