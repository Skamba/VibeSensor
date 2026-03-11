# ruff: noqa: E402, E501
from __future__ import annotations

"""Runtime queue/history tracking and export-filter regressions."""


from pathlib import Path

import pytest
from _paths import SERVER_ROOT

from vibesensor.analysis.helpers import _weighted_percentile
from vibesensor.analysis.test_plan import _weighted_percentile_speed
from vibesensor.history_db import HistoryDB
from vibesensor.processing import SignalProcessor


# ---------------------------------------------------------------------------
# Fix 1 – SQLite busy_timeout is set
# ---------------------------------------------------------------------------
class TestSQLiteBusyTimeout:
    def test_busy_timeout_is_set(self, tmp_path: Path) -> None:
        """HistoryDB must set PRAGMA busy_timeout to avoid immediate SQLITE_BUSY."""
        db = HistoryDB(tmp_path / "test.db")
        try:
            result = db._conn.execute("PRAGMA busy_timeout").fetchone()
            assert result is not None
            assert result[0] == 5000
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Fix 2 – flush_client_buffer bumps ingest_generation
# ---------------------------------------------------------------------------
class TestFlushBumpsGeneration:
    def test_flush_increments_ingest_generation(self) -> None:
        """Flushing a buffer must bump ingest_generation to invalidate stale caches."""
        proc = SignalProcessor(
            sample_rate_hz=400,
            waveform_seconds=2,
            waveform_display_hz=50,
            fft_n=512,
        )
        with proc._store.lock:
            buf = proc._store._get_or_create_unlocked("sensor-1")
        buf.ingest_generation = 5
        buf.count = 10  # pretend some data
        proc.flush_client_buffer("sensor-1")
        assert buf.ingest_generation == 6


# ---------------------------------------------------------------------------
# Fix 5 – Dead functions removed
# ---------------------------------------------------------------------------
_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_page1.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram_render.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram_render.py", "def _format_db"),
    ("vibesensor/update/firmware_cache.py", "def install_baseline"),
]


class TestDeadFunctionsRemoved:
    @pytest.mark.parametrize(
        ("rel_path", "forbidden"),
        _DEAD_FUNCTION_CASES,
        ids=[c[1] for c in _DEAD_FUNCTION_CASES],
    )
    def test_dead_function_absent(self, rel_path: str, forbidden: str) -> None:
        text = (SERVER_ROOT / rel_path).read_text()
        assert forbidden not in text


# ---------------------------------------------------------------------------
# Fix 6 – normalize_lang consolidated in report_i18n (canonical source)
# ---------------------------------------------------------------------------
class TestNormalizeLangArchitecturalBoundary:
    _SUMMARY_SRC = SERVER_ROOT / "vibesensor" / "analysis" / "summary_builder.py"

    def test_summary_imports_normalize_lang_from_report_i18n(self) -> None:
        """summary_builder.py must import normalize_lang from report_i18n (single source)."""
        assert "from ..report_i18n import normalize_lang" in self._SUMMARY_SRC.read_text()

    def test_summary_does_not_define_own_normalize_lang(self) -> None:
        """summary_builder.py must NOT define its own normalize_lang."""
        assert "def normalize_lang" not in self._SUMMARY_SRC.read_text()


# ---------------------------------------------------------------------------
# Fix 7 – Export ZIP filters internal _-prefixed analysis fields
# ---------------------------------------------------------------------------
class TestExportZipFiltersInternals:
    def test_underscore_fields_stripped_in_source(self) -> None:
        """Export assembly must strip _-prefixed analysis keys before zipping details."""
        helper_text = (SERVER_ROOT / "vibesensor" / "history_services" / "helpers.py").read_text()
        export_text = (SERVER_ROOT / "vibesensor" / "history_services" / "exports.py").read_text()
        assert 'if not key.startswith("_")' in helper_text
        assert "strip_internal_fields(analysis)" in export_text


# ---------------------------------------------------------------------------
# Fix 8 – _weighted_percentile_speed delegates to _weighted_percentile
# ---------------------------------------------------------------------------
class TestWeightedPercentileDedup:
    def test_weighted_percentile_speed_delegates(self) -> None:
        """_weighted_percentile_speed should produce same results as _weighted_percentile for positive speeds."""
        pairs = [(60.0, 2.0), (80.0, 3.0), (100.0, 1.0)]
        for q in [0.0, 0.1, 0.5, 0.9, 1.0]:
            result = _weighted_percentile_speed(pairs, q)
            expected = _weighted_percentile(pairs, q)
            assert result == expected, f"Mismatch at q={q}: {result} != {expected}"

    def test_weighted_percentile_speed_filters_negative(self) -> None:
        pairs = [(-10.0, 5.0), (50.0, 1.0)]
        result = _weighted_percentile_speed(pairs, 0.5)
        assert result == 50.0


# ---------------------------------------------------------------------------
# Fix 9 – _analysis_queue is non-evicting
# ---------------------------------------------------------------------------
class TestAnalysisQueueContract:
    def test_analysis_queue_is_not_bounded_or_evicted(self) -> None:
        """PostAnalysisWorker._analysis_queue must not silently evict queued runs."""
        text = (SERVER_ROOT / "vibesensor" / "metrics_log" / "post_analysis.py").read_text()
        assert "self._analysis_queue: deque[_QueuedRun] = deque()" in text
        assert "evicting run" not in text
