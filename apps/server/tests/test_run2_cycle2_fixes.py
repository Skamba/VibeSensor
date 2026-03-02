# ruff: noqa: E501
"""Tests for run-2 Cycle 2 fixes: busy_timeout, flush gen bump, deque, pruning, dedup, export filter."""

from __future__ import annotations

from collections import deque
from pathlib import Path


# ---------------------------------------------------------------------------
# Fix 1 – SQLite busy_timeout is set
# ---------------------------------------------------------------------------
class TestSQLiteBusyTimeout:
    def test_busy_timeout_is_set(self, tmp_path: Path) -> None:
        """HistoryDB must set PRAGMA busy_timeout to avoid immediate SQLITE_BUSY."""
        from vibesensor.history_db import HistoryDB

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
        from vibesensor.processing import SignalProcessor

        proc = SignalProcessor(
            sample_rate_hz=400,
            waveform_seconds=2,
            waveform_display_hz=50,
            fft_n=512,
        )
        buf = proc._get_or_create("sensor-1")
        buf.ingest_generation = 5
        buf.count = 10  # pretend some data
        proc.flush_client_buffer("sensor-1")
        assert buf.ingest_generation == 6


# ---------------------------------------------------------------------------
# Fix 3 – _phase_speed_history is a deque with maxlen
# ---------------------------------------------------------------------------
class TestPhaseSpeedHistoryDeque:
    def test_is_deque_with_maxlen(self) -> None:
        from vibesensor.live_diagnostics import LiveDiagnosticsEngine

        engine = LiveDiagnosticsEngine()
        assert isinstance(engine._phase_speed_history, deque)
        assert engine._phase_speed_history.maxlen is not None
        assert engine._phase_speed_history.maxlen > 0

    def test_reset_preserves_deque(self) -> None:
        from vibesensor.live_diagnostics import LiveDiagnosticsEngine

        engine = LiveDiagnosticsEngine()
        engine.reset()
        assert isinstance(engine._phase_speed_history, deque)
        assert engine._phase_speed_history.maxlen is not None


# ---------------------------------------------------------------------------
# Fix 4 – _sensor_trackers pruning after silence
# ---------------------------------------------------------------------------
class TestSensorTrackersPruning:
    def test_stale_trackers_are_pruned(self) -> None:
        """Trackers not seen for many ticks should be removed."""
        from vibesensor.live_diagnostics import LiveDiagnosticsEngine, _TrackerLevelState

        engine = LiveDiagnosticsEngine()
        tracker = _TrackerLevelState()
        engine._sensor_trackers["stale:key"] = tracker
        # Simulate 60 ticks of silence (not in seen set)
        for _ in range(60):
            engine._decay_unseen_sensor_trackers(set())
        assert "stale:key" not in engine._sensor_trackers

    def test_seen_trackers_not_pruned(self) -> None:
        from vibesensor.live_diagnostics import LiveDiagnosticsEngine, _TrackerLevelState

        engine = LiveDiagnosticsEngine()
        tracker = _TrackerLevelState()
        engine._sensor_trackers["active:key"] = tracker
        for _ in range(100):
            engine._decay_unseen_sensor_trackers({"active:key"})
        assert "active:key" in engine._sensor_trackers


# ---------------------------------------------------------------------------
# Fix 5 – Dead functions removed
# ---------------------------------------------------------------------------
class TestDeadFunctionsRemoved:
    def test_no_measure_text_height(self) -> None:
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "report" / "pdf_builder.py"
        text = src.read_text()
        assert "_measure_text_height" not in text

    def test_no_amp_heat_color(self) -> None:
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "report" / "pdf_diagram.py"
        text = src.read_text()
        assert "_amp_heat_color" not in text

    def test_no_format_db_in_diagram(self) -> None:
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "report" / "pdf_diagram.py"
        text = src.read_text()
        assert "def _format_db" not in text

    def test_no_install_baseline(self) -> None:
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "firmware_cache.py"
        text = src.read_text()
        assert "def install_baseline" not in text


# ---------------------------------------------------------------------------
# Fix 6 – _normalize_lang: kept inline per architectural boundary
# ---------------------------------------------------------------------------
class TestNormalizeLangArchitecturalBoundary:
    def test_summary_does_not_import_report_i18n(self) -> None:
        """summary.py must NOT import from report_i18n (i18n separation constraint)."""
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "analysis" / "summary.py"
        text = src.read_text()
        assert "from ..report_i18n import" not in text

    def test_summary_has_inline_normalize_lang(self) -> None:
        """summary.py must define its own _normalize_lang (avoiding report_i18n dep)."""
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "analysis" / "summary.py"
        text = src.read_text()
        assert "def _normalize_lang" in text


# ---------------------------------------------------------------------------
# Fix 7 – Export ZIP filters internal _-prefixed analysis fields
# ---------------------------------------------------------------------------
class TestExportZipFiltersInternals:
    def test_underscore_fields_stripped_in_source(self) -> None:
        """history route module must filter _-prefixed keys from analysis before export."""
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "routes" / "history.py"
        text = src.read_text()
        assert 'not k.startswith("_")' in text


# ---------------------------------------------------------------------------
# Fix 8 – _weighted_percentile_speed delegates to _weighted_percentile
# ---------------------------------------------------------------------------
class TestWeightedPercentileDedup:
    def test_weighted_percentile_speed_delegates(self) -> None:
        """_weighted_percentile_speed should produce same results as _weighted_percentile for positive speeds."""
        from vibesensor.analysis.findings import _weighted_percentile
        from vibesensor.analysis.test_plan import _weighted_percentile_speed

        pairs = [(60.0, 2.0), (80.0, 3.0), (100.0, 1.0)]
        for q in [0.0, 0.1, 0.5, 0.9, 1.0]:
            result = _weighted_percentile_speed(pairs, q)
            expected = _weighted_percentile(pairs, q)
            assert result == expected, f"Mismatch at q={q}: {result} != {expected}"

    def test_weighted_percentile_speed_filters_negative(self) -> None:
        from vibesensor.analysis.test_plan import _weighted_percentile_speed

        pairs = [(-10.0, 5.0), (50.0, 1.0)]
        result = _weighted_percentile_speed(pairs, 0.5)
        assert result == 50.0


# ---------------------------------------------------------------------------
# Fix 9 – _analysis_queue has maxlen
# ---------------------------------------------------------------------------
class TestAnalysisQueueMaxlen:
    def test_analysis_queue_has_maxlen(self) -> None:
        """PostAnalysisWorker._analysis_queue must have a bounded maxlen."""
        src = Path(__file__).resolve().parent.parent / "vibesensor" / "metrics_log" / "post_analysis.py"
        text = src.read_text()
        assert "_analysis_queue: deque[str] = deque(maxlen=" in text
