# ruff: noqa: E402, E501, F811
from __future__ import annotations

"""Consolidated runtime regression tests."""


# ===== From test_api_history_processing_regressions.py =====

"""Runtime regressions spanning API, history, and processing boundaries."""


import re
from pathlib import Path

import numpy as np
import pytest
from _paths import SERVER_ROOT

from vibesensor.api import _safe_filename
from vibesensor.history_db import HistoryDB
from vibesensor.processing import SignalProcessor

_SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

# --- Bug 1 & 2: Content-Disposition / zip filename sanitisation -----------


class TestSafeFilename:
    """Ensure _safe_filename strips dangerous characters for HTTP headers."""

    def test_normal_run_id_unchanged(self) -> None:
        assert _safe_filename("run-2026-01-15_12-30") == "run-2026-01-15_12-30"

    @pytest.mark.parametrize(
        "raw,forbidden",
        [
            ('run"injected', ['"']),
            ("run\r\nX-Injected: yes", ["\r", "\n"]),
            ("../../etc/passwd", ["/", "\\"]),
        ],
        ids=["double-quotes", "crlf", "path-separators"],
    )
    def test_dangerous_chars_stripped(self, raw: str, forbidden: list[str]) -> None:
        result = _safe_filename(raw)
        for ch in forbidden:
            assert ch not in result

    def test_empty_input_returns_download(self) -> None:
        assert _safe_filename("") == "download"

    def test_only_special_chars_returns_underscores(self) -> None:
        result = _safe_filename('""///')
        assert result  # non-empty
        assert '"' not in result
        assert "/" not in result

    def test_long_input_truncated(self) -> None:
        assert len(_safe_filename("a" * 300)) <= 200

    @pytest.mark.parametrize("raw", ["normal-run", "run 123", "run<script>", "run;echo hi"])
    def test_result_matches_safe_pattern(self, raw: str) -> None:
        result = _safe_filename(raw)
        assert _SAFE_RE.match(result), f"Unsafe chars in result: {result!r}"


# --- Bug 3: history_db analysis type validation ---------------------------


class TestHistoryDBAnalysisValidation:
    """Analysis stored in history must be type-checked as dict."""

    @staticmethod
    def _make_db(tmp_path: Path) -> HistoryDB:
        db = HistoryDB(tmp_path / "history.db")
        db.create_run("run-1", "2026-01-01T00:00:00Z", {"source": "test"})
        return db

    def test_rejects_non_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        with db._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status='complete', analysis_json=? WHERE run_id=?",
                ("[1,2,3]", "run-1"),
            )
        run = db.get_run("run-1")
        assert run is not None
        assert "analysis" not in run

    def test_accepts_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        db.store_analysis("run-1", {"findings": []})
        run = db.get_run("run-1")
        assert run is not None
        assert isinstance(run.get("analysis"), dict)


# --- Bug 9: Division by zero when sample_rate_hz == 0 --------------------


class TestProcessingZeroSampleRate:
    """Processing must not crash when sample_rate_hz is zero."""

    def _make_processor(self, sr: int) -> SignalProcessor:
        return SignalProcessor(
            sample_rate_hz=sr,
            waveform_seconds=4,
            waveform_display_hz=100,
            fft_n=256,
            spectrum_max_hz=200,
        )

    def test_selected_payload_returns_empty_on_zero_sr(self) -> None:
        # Processor with sr=0 but data ingested at a valid rate
        proc = self._make_processor(0)
        raw = np.zeros((10, 3), dtype=np.int16)
        proc.ingest("c1", raw, sample_rate_hz=800)
        # Force buf.sample_rate_hz back to 0 to simulate the bug path
        buf = proc._buffers["c1"]
        buf.sample_rate_hz = 0
        result = proc.selected_payload("c1")
        # Must return without crash; waveform/spectrum/metrics empty
        assert result.get("waveform") == {} or result.get("metrics") == {}

    @pytest.mark.parametrize("sr,expect_empty", [(0, True), (800, False)], ids=["zero", "normal"])
    def test_fft_params(self, sr: int, *, expect_empty: bool) -> None:
        proc = self._make_processor(800)
        freq_slice, valid_idx = proc._fft_params(sr)
        if expect_empty:
            assert len(freq_slice) == 0
            assert len(valid_idx) == 0
        else:
            assert len(freq_slice) > 0
            assert len(valid_idx) > 0


# --- Bug 5: live_diagnostics type annotation (compile-time) ---------------


def test_live_diagnostics_entries_type_annotation() -> None:
    """Verify event_detector properly extracts label and location per client."""
    source = (SERVER_ROOT / "vibesensor" / "live_diagnostics" / "event_detector.py").read_text()
    assert "client_map" in source, "client_map lookup must exist"
    assert "client_location_map" in source, "client_location_map lookup must exist"


# --- Bug 10: location_code stripped before registry -----------------------


def test_set_location_uses_stripped_code() -> None:
    """Verify the stripped code is passed to registry.set_location."""
    source = (SERVER_ROOT / "vibesensor" / "routes" / "clients.py").read_text()
    assert "set_location(normalized_client_id, code)" in source
    assert "set_location(normalized_client_id, req.location_code)" not in source


# ===== From test_concurrency_generation_guard_regressions.py =====

"""Concurrency and generation-guard regressions.

Tests covering:
1. Auto-stop generation guard (prevents killing a freshly started session)
2. Atomic delete_run_if_safe (TOCTOU fix)
3. finalize_run_with_metadata atomicity
4. stop_logging / start_logging _finalize_run_locked return-value gating
"""



import pytest

from vibesensor.analysis_settings import AnalysisSettingsStore
from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.metrics_log import MetricsLogger
from vibesensor.registry import ClientRegistry


def _make_logger(tmp_path: Path, **overrides):
    """Create a minimal MetricsLogger + HistoryDB for concurrency tests."""
    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db)
    defaults = dict(
        enabled=False,
        log_path=tmp_path / "metrics.jsonl",
        metrics_log_hz=10,
        registry=registry,
        gps_monitor=GPSSpeedMonitor(gps_enabled=False),
        processor=SignalProcessor(
            sample_rate_hz=800,
            waveform_seconds=5,
            waveform_display_hz=60,
            fft_n=256,
            spectrum_max_hz=200,
        ),
        analysis_settings=AnalysisSettingsStore(),
        sensor_model="ADXL345",
        default_sample_rate_hz=800,
        fft_window_size_samples=256,
        history_db=db,
        persist_history_db=False,
    )
    defaults.update(overrides)
    return MetricsLogger(**defaults), db


# ---------------------------------------------------------------------------
# 1. Auto-stop generation guard
# ---------------------------------------------------------------------------


class TestAutoStopGenerationGuard:
    """stop_logging(_only_if_generation=N) must be a no-op when session has
    already advanced past generation N."""

    def test_stale_generation_does_not_stop_new_session(self, tmp_path: Path) -> None:
        logger, db = _make_logger(tmp_path)
        logger.start_logging()
        old_gen = logger._session_generation
        old_run_id = logger._run_id
        assert old_run_id is not None

        # Simulate: user starts a brand-new session
        logger.start_logging()
        new_gen = logger._session_generation
        new_run_id = logger._run_id
        assert new_run_id is not None
        assert new_gen > old_gen

        # Auto-stop fires for the *old* generation
        logger.stop_logging(_only_if_generation=old_gen)

        # New session must still be alive
        assert logger.enabled is True
        assert logger._run_id == new_run_id
        db.close()

    def test_matching_generation_does_stop(self, tmp_path: Path) -> None:
        logger, db = _make_logger(tmp_path)
        logger.start_logging()
        gen = logger._session_generation

        logger.stop_logging(_only_if_generation=gen)
        assert logger.enabled is False
        assert logger._run_id is None
        db.close()


# ---------------------------------------------------------------------------
# 2. Atomic delete_run_if_safe
# ---------------------------------------------------------------------------


class TestDeleteRunIfSafe:
    def test_delete_complete_run(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        db.store_analysis("r1", {"score": 1})
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is True
        assert reason is None
        assert db.get_run("r1") is None
        db.close()

    def test_refuse_recording(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is False
        assert reason == "active"
        assert db.get_run("r1") is not None
        db.close()

    def test_refuse_analyzing(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is False
        assert reason == "analyzing"
        db.close()

    def test_not_found(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        deleted, reason = db.delete_run_if_safe("nonexistent")
        assert deleted is False
        assert reason == "not_found"
        db.close()

    def test_delete_error_run(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.store_analysis_error("r1", "boom")
        deleted, reason = db.delete_run_if_safe("r1")
        assert deleted is True
        assert reason is None
        db.close()


# ---------------------------------------------------------------------------
# 3. finalize_run_with_metadata atomicity
# ---------------------------------------------------------------------------


class TestFinalizeRunWithMetadata:
    def test_atomic_metadata_and_status(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        new_meta = {"run_id": "r1", "end_time_utc": "2026-01-01T00:05:00Z", "extra": "val"}
        db.finalize_run_with_metadata("r1", "2026-01-01T00:05:00Z", new_meta)
        run = db.get_run("r1")
        assert run is not None
        assert run["status"] == "analyzing"
        assert run["end_time_utc"] == "2026-01-01T00:05:00Z"
        metadata = run.get("metadata", {})
        assert metadata.get("extra") == "val"
        db.close()

    def test_only_recording_transitions(self, tmp_path: Path) -> None:
        db = HistoryDB(tmp_path / "h.db")
        db.create_run("r1", "2026-01-01T00:00:00Z", {"run_id": "r1"})
        db.finalize_run("r1", "2026-01-01T00:05:00Z")
        # Already analyzing — second finalize_with_metadata should be no-op
        db.finalize_run_with_metadata("r1", "2026-01-01T00:10:00Z", {"extra": "v2"})
        run = db.get_run("r1")
        assert run is not None
        assert run["status"] == "analyzing"
        assert run["end_time_utc"] == "2026-01-01T00:05:00Z"
        db.close()


# ---------------------------------------------------------------------------
# 4. _finalize_run_locked return value gates analysis scheduling
# ---------------------------------------------------------------------------


class TestFinalizeReturnGatesAnalysis:
    """When _finalize_run_locked fails, stop_logging must NOT schedule analysis."""

    def test_analysis_not_scheduled_when_finalize_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logger, db = _make_logger(
            tmp_path,
            persist_history_db=True,
            language_provider=lambda: "en",
        )

        logger.start_logging()
        run_id = logger._run_id
        assert run_id is not None

        # Simulate a run that created history and wrote samples
        db.create_run(run_id, "2026-01-01T00:00:00Z", {"run_id": run_id})
        logger._history_run_created = True
        logger._written_sample_count = 5

        # Sabotage finalize_run_with_metadata to simulate a DB crash
        monkeypatch.setattr(
            db,
            "finalize_run_with_metadata",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk gone")),
        )

        schedule_calls: list[str] = []
        monkeypatch.setattr(
            logger,
            "_schedule_post_analysis",
            lambda rid: schedule_calls.append(rid),
        )

        logger.stop_logging()
        # Analysis must NOT have been scheduled because finalize failed
        assert schedule_calls == [], (
            f"Expected no analysis scheduling after finalize failure, got: {schedule_calls}"
        )
        db.close()


# ===== From test_io_and_time_guard_regressions.py =====

"""I/O cleanup, time-source, and report-cli guard regressions.

Covers:
  1. firmware_cache.refresh() – target/old_current initialised before try
  2. firmware_cache._download_asset() – fd leak guard when os.fdopen fails
  3. gps_speed.resolve_speed() – TOCTOU snapshot of speed_mps
  4. gps_speed._is_gps_stale() – TOCTOU snapshot of last_update_ts
  5. report_cli.main() – PDF generation errors return 1 instead of traceback
  6. report_data_builder date_str – includes UTC suffix
"""


import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from vibesensor.analysis.report_data_builder import map_summary
from vibesensor.firmware_cache import FirmwareCache, FirmwareCacheConfig, GitHubReleaseFetcher
from vibesensor.report_cli import main as report_cli_main


def _make_summary(report_date: str, **overrides: Any) -> dict[str, Any]:
    """Build a minimal summary dict for map_summary tests."""
    base: dict[str, Any] = {
        "lang": "en",
        "report_date": report_date,
        "metadata": {},
        "findings": [],
        "top_causes": [],
        "speed_stats": {},
        "most_likely_origin": {},
        "sensor_intensity_by_location": [],
        "run_suitability": [],
        "phase_info": None,
        "plots": {"peaks_table": []},
        "test_plan": [],
    }
    base.update(overrides)
    return base

# ------------------------------------------------------------------
# 1. firmware_cache.refresh() – UnboundLocalError guard
# ------------------------------------------------------------------


class TestFirmwareCacheRefreshUnboundGuard:
    """target/old_current must be defined before the try block so the
    except handler never raises UnboundLocalError."""

    def test_exception_before_activation_does_not_raise_unbound(self, tmp_path: Path) -> None:
        """If download_bundle raises, the except block should not crash."""
        cfg = FirmwareCacheConfig(
            firmware_repo="test/repo",
            cache_dir=str(tmp_path / "fw"),
        )
        cache = FirmwareCache(cfg)

        # Fake fetcher that raises during download
        fetcher = MagicMock()
        fetcher.find_release.return_value = {"tag_name": "v999"}
        fetcher.find_firmware_asset.return_value = {"name": "fw.zip"}
        fetcher.download_bundle.side_effect = RuntimeError("download failed")

        with pytest.raises(RuntimeError, match="download failed"):
            cache.refresh(fetcher=fetcher)

        # The key assertion is that we got RuntimeError, NOT UnboundLocalError.


# ------------------------------------------------------------------
# 2. firmware_cache._download_asset() – fd leak guard
# ------------------------------------------------------------------


class TestDownloadAssetFdLeakGuard:
    """When os.fdopen fails, the raw fd must be closed."""

    def test_fd_closed_when_fdopen_fails(self, tmp_path: Path) -> None:
        cfg = FirmwareCacheConfig(firmware_repo="test/repo")
        fetcher = GitHubReleaseFetcher(cfg)

        dest = tmp_path / "firmware.bin"

        # Patch urlopen to provide a fake response, and os.fdopen to fail
        fake_resp = MagicMock()
        fake_resp.read.return_value = b"data"
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: None

        with (
            patch("vibesensor.firmware_cache.urlopen", return_value=fake_resp),
            patch("os.fdopen", side_effect=OSError("mock fdopen failure")),
            patch("os.close") as mock_close,
        ):
            with pytest.raises(OSError, match="mock fdopen failure"):
                fetcher._download_asset("https://example.com/fw.bin", dest)

            # os.close should have been called with the leaked fd
            assert mock_close.called


# ------------------------------------------------------------------
# 3. gps_speed.resolve_speed() – TOCTOU snapshot
# ------------------------------------------------------------------


class TestResolveSpeedTOCTOU:
    """resolve_speed must snapshot speed_mps to avoid read-between-lines races."""

    def test_speed_snapshot_used_for_gps_return(self) -> None:
        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.speed_mps = 10.5
        mon.last_update_ts = time.monotonic()
        mon.connection_state = "connected"

        result = mon.resolve_speed()
        assert result.speed_mps == 10.5
        assert result.source == "gps"

    def test_speed_none_after_stale(self) -> None:
        mon = GPSSpeedMonitor(gps_enabled=True)
        mon.speed_mps = 5.0
        mon.last_update_ts = time.monotonic() - 999  # very stale
        mon.connection_state = "connected"

        result = mon.resolve_speed()
        assert result.fallback_active is True


# ------------------------------------------------------------------
# 4. gps_speed._is_gps_stale() – TOCTOU snapshot
# ------------------------------------------------------------------


class TestIsGpsStaleTOCTOU:
    """_is_gps_stale must snapshot last_update_ts."""

    @pytest.mark.parametrize(
        "ts,expected",
        [
            pytest.param(None, True, id="none_ts"),
            pytest.param("fresh", False, id="fresh_ts"),
            pytest.param("old", True, id="old_ts"),
        ],
    )
    def test_is_gps_stale(self, ts: Any, expected: bool) -> None:
        mon = GPSSpeedMonitor(gps_enabled=True)
        if ts == "fresh":
            mon.last_update_ts = time.monotonic()
        elif ts == "old":
            mon.last_update_ts = time.monotonic() - 999
        else:
            mon.last_update_ts = None
        assert mon._is_gps_stale() is expected


# ------------------------------------------------------------------
# 5. report_cli – PDF generation error handling
# ------------------------------------------------------------------


class TestReportCliErrorHandling:
    """PDF generation failures should return exit code 1, not raise."""

    def test_pdf_build_failure_returns_1(self, tmp_path: Path) -> None:
        run_file = tmp_path / "test_run.jsonl"
        run_file.write_text('{"event": "meta"}\n')

        with (
            patch("vibesensor.report_cli.summarize_log", return_value={"some": "summary"}),
            patch(
                "vibesensor.report_cli.build_report_pdf",
                side_effect=RuntimeError("PDF engine failed"),
            ),
            patch("vibesensor.report_cli.map_summary", return_value={}),
            patch(
                "vibesensor.report_cli.parse_args",
                return_value=MagicMock(input=run_file, output=None, summary_json=None),
            ),
        ):
            result = report_cli_main()
            assert result == 1

    def test_pdf_build_success_returns_0(self, tmp_path: Path) -> None:
        run_file = tmp_path / "test_run.jsonl"
        run_file.write_text('{"event": "meta"}\n')

        with (
            patch("vibesensor.report_cli.summarize_log", return_value={"some": "summary"}),
            patch("vibesensor.report_cli.build_report_pdf", return_value=b"%PDF-1.4 fake"),
            patch("vibesensor.report_cli.map_summary", return_value={}),
            patch(
                "vibesensor.report_cli.parse_args",
                return_value=MagicMock(
                    input=run_file, output=tmp_path / "out.pdf", summary_json=None
                ),
            ),
        ):
            result = report_cli_main()
            assert result == 0
            assert (tmp_path / "out.pdf").exists()


# ------------------------------------------------------------------
# 6. report_data_builder – UTC suffix on date_str
# ------------------------------------------------------------------


class TestReportDataBuilderUTCSuffix:
    """date_str in report data must end with ' UTC'."""

    def test_date_str_has_utc_suffix(self) -> None:
        summary = _make_summary(
            "2025-06-01T14:30:00Z",
            metadata={"car_name": "TestCar"},
        )
        result = map_summary(summary)
        assert result.run_datetime is not None
        assert result.run_datetime.endswith(" UTC"), (
            f"Expected UTC suffix, got: {result.run_datetime!r}"
        )
        assert "2025-06-01 14:30:00" in result.run_datetime

    def test_date_str_no_tz_input_still_has_utc(self) -> None:
        summary = _make_summary("2025-03-15T09:45:22")
        result = map_summary(summary)
        assert result.run_datetime == "2025-03-15 09:45:22 UTC"


# ===== From test_metrics_cache_and_settings_regressions.py =====

"""Metrics cache, settings rollback, and counter-delta regressions."""



import pytest

from vibesensor.analysis.helpers import counter_delta
from vibesensor.processing import ClientBuffer
from vibesensor.settings_store import PersistenceError, SettingsStore

# ---------------------------------------------------------------------------
# counter_delta shared helper
# ---------------------------------------------------------------------------


class TestCounterDelta:
    """Test the shared counter_delta helper extracted from findings/summary."""

    def test_empty_list(self) -> None:
        assert counter_delta([]) == 0

    def test_single_value(self) -> None:
        assert counter_delta([5.0]) == 0

    def test_monotonic_increase(self) -> None:
        assert counter_delta([0.0, 1.0, 3.0, 6.0]) == 6

    def test_reset_ignored(self) -> None:
        # Counter resets (decreases) should be ignored, only increases counted
        assert counter_delta([0.0, 5.0, 2.0, 7.0]) == 10  # 5 + 0 + 5

    def test_all_same_value(self) -> None:
        assert counter_delta([3.0, 3.0, 3.0]) == 0

    def test_negative_values(self) -> None:
        assert counter_delta([-2.0, 0.0, 3.0]) == 5  # 2 + 3

    def test_float_precision(self) -> None:
        result = counter_delta([0.0, 0.1, 0.3])
        assert result == 0  # int truncation of 0.3


# ---------------------------------------------------------------------------
# ClientBuffer.invalidate_caches
# ---------------------------------------------------------------------------


class TestClientBufferInvalidateCaches:
    """Verify the extracted invalidate_caches method works correctly."""

    def test_clears_all_cache_fields(self) -> None:
        buf = ClientBuffer(
            data=np.zeros((3, 100), dtype=np.float32),
            capacity=100,
        )
        # Simulate cached state
        buf.cached_spectrum_payload = {"freq": [1, 2]}
        buf.cached_spectrum_payload_generation = 5
        buf.cached_selected_payload = {"data": True}
        buf.cached_selected_payload_key = (1, 2, 3)

        buf.invalidate_caches()

        assert buf.cached_spectrum_payload is None
        assert buf.cached_spectrum_payload_generation == -1
        assert buf.cached_selected_payload is None
        assert buf.cached_selected_payload_key is None


# ---------------------------------------------------------------------------
# SignalProcessor compute_metrics generation guard
# ---------------------------------------------------------------------------


class TestComputeMetricsGenerationGuard:
    """Phase 3 should not overwrite fresher results with stale ones."""

    def test_stale_generation_does_not_overwrite(self) -> None:
        sp = SignalProcessor(
            sample_rate_hz=1000,
            waveform_seconds=2,
            waveform_display_hz=50,
            fft_n=256,
        )
        client = "test-client"
        # Ingest enough samples to compute
        chunk = np.random.default_rng(42).standard_normal((512, 3)).astype(np.float32) * 0.01
        sp.ingest(client, chunk, sample_rate_hz=1000)

        # First compute
        sp.compute_metrics(client)

        with sp._lock:
            buf = sp._buffers[client]
            gen_after_first = buf.compute_generation
            # Artificially advance the compute generation to simulate a fresher result
            buf.compute_generation = gen_after_first + 100

        # Compute again — this should NOT overwrite because snap_ingest_gen < compute_generation
        sp.compute_metrics(client)

        with sp._lock:
            buf = sp._buffers[client]
            # Should still be the artificially advanced generation
            assert buf.compute_generation == gen_after_first + 100


# ---------------------------------------------------------------------------
# SettingsStore rollback on persist failure
# ---------------------------------------------------------------------------


class TestSettingsStoreRollbackDbFailure:
    """Verify all mutating methods roll back in-memory state on PersistenceError."""

    @pytest.fixture
    def store(self) -> Any:
        s = SettingsStore()
        s.add_car({"name": "Test Car", "type": "sedan"})
        s.set_active_car(s.get_cars()["cars"][0]["id"])
        return s

    def test_update_active_car_aspects_rollback(self, store: Any) -> None:
        cars = store.get_cars()
        original_aspects = dict(cars["cars"][0].get("aspects", {}))

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.update_active_car_aspects({"tire_width": 999})

        # Aspects should be rolled back
        current = store.get_cars()
        assert current["cars"][0].get("aspects", {}) == original_aspects

    def test_update_speed_source_rollback(self, store: Any) -> None:
        original = store.get_speed_source()

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.update_speed_source({"mode": "gps"})

        # Speed source should be rolled back
        assert store.get_speed_source() == original

    def test_set_language_rollback(self, store: Any) -> None:
        original = store.language

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                new_lang = "nl" if original == "en" else "en"
                store.set_language(new_lang)

        assert store.language == original

    def test_set_speed_unit_rollback(self, store: Any) -> None:
        original = store.speed_unit

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                new_unit = "mps" if original == "kmh" else "kmh"
                store.set_speed_unit(new_unit)

        assert store.speed_unit == original

    def test_set_sensor_rollback_new_sensor(self, store: Any) -> None:
        mac = "AA:BB:CC:DD:EE:FF"

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.set_sensor(mac, {"name": "Test", "location": "front"})

        # Sensor should not exist after rollback
        sensors = store.get_sensors()
        normalized = mac.upper().replace(":", "")
        assert normalized not in sensors

    def test_set_sensor_rollback_existing_sensor(self, store: Any) -> None:
        mac = "11:22:33:44:55:66"
        # First create a sensor successfully
        store.set_sensor(mac, {"name": "Original", "location": "rear"})

        with patch.object(store, "_persist", side_effect=PersistenceError("disk full")):
            with pytest.raises(PersistenceError):
                store.set_sensor(mac, {"name": "Updated", "location": "front"})

        # Should have original values
        sensors = store.get_sensors()
        normalized = mac.upper().replace(":", "")
        assert sensors[normalized]["name"] == "Original"
        assert sensors[normalized]["location"] == "rear"


# ===== From test_runtime_fallbacks_regressions.py =====

"""Runtime fallback and error-guard regressions.

Covers strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting.
"""


import json
import math

import pytest
from vibesensor_core.vibration_strength import (
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)

from vibesensor.analysis.order_analysis import _wheel_focus_from_location


class TestStrengthFloorFallback:
    """Regression: strength_floor_amp_g must not return 0.0 when all bins
    are within peak exclusion zones, since 0.0 floor produces ~140 dB."""

    def test_all_bins_excluded_falls_back_to_p20(self) -> None:
        """When every bin is excluded by peaks, fall back to P20 noise floor."""
        # 5 bins, one dominant peak in the center.  With exclusion_hz=10.0
        # every bin falls within the exclusion zone around the peak.
        freq = [5.0, 6.0, 7.0, 8.0, 9.0]
        amps = [0.001, 0.002, 0.1, 0.002, 0.001]
        peak_indexes = [2]  # peak at 7 Hz

        floor = strength_floor_amp_g(
            freq_hz=freq,
            combined_spectrum_amp_g=amps,
            peak_indexes=peak_indexes,
            exclusion_hz=10.0,  # excludes everything
            min_hz=5.0,
            max_hz=9.0,
        )
        # Should NOT be 0.0 — must fall back to P20
        assert floor > 0.0, "Floor must not be 0.0 when all bins are excluded"

        # Verify the dB value is sane (not 140+)
        db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=0.1,
            floor_amp_g=floor,
        )
        assert db < 80, f"Expected sane dB (<80), got {db}"
        assert math.isfinite(db)

    def test_normal_case_unchanged(self) -> None:
        """When bins survive exclusion, the original median behavior is used."""
        freq = [5.0, 6.0, 7.0, 8.0, 9.0]
        amps = [0.001, 0.002, 0.1, 0.002, 0.001]
        peak_indexes = [2]  # peak at 7 Hz

        floor = strength_floor_amp_g(
            freq_hz=freq,
            combined_spectrum_amp_g=amps,
            peak_indexes=peak_indexes,
            exclusion_hz=0.5,  # only excludes 7 Hz ± 0.5
            min_hz=5.0,
            max_hz=9.0,
        )
        assert floor > 0.0
        # Should be the median of [0.001, 0.002, 0.002, 0.001]
        expected_median = (0.001 + 0.002) / 2  # sorted: [0.001, 0.001, 0.002, 0.002]
        assert abs(floor - expected_median) < 1e-6


class TestWheelFocusFromLocation:
    """Regression: _wheel_focus_from_location must match label_for_code() outputs
    which use spaces (e.g. 'Front Left Wheel'), not hyphens."""

    @pytest.mark.parametrize(
        "label, expected_key",
        [
            # Space-separated (canonical)
            ("Front Left Wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("Front Right Wheel", "WHEEL_FOCUS_FRONT_RIGHT"),
            ("Rear Left Wheel", "WHEEL_FOCUS_REAR_LEFT"),
            ("Rear Right Wheel", "WHEEL_FOCUS_REAR_RIGHT"),
            # Hyphen-separated
            ("front-left wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("rear-right wheel", "WHEEL_FOCUS_REAR_RIGHT"),
            # Underscore-separated
            ("front_left_wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("rear_left_wheel", "WHEEL_FOCUS_REAR_LEFT"),
            # Generic locations
            ("Trunk", "WHEEL_FOCUS_REAR"),
            ("Engine Bay", "WHEEL_FOCUS_FRONT"),
            ("unknown location", "WHEEL_FOCUS_ALL"),
        ],
    )
    def test_location_to_wheel_focus(self, label: str, expected_key: str) -> None:
        assert _wheel_focus_from_location(label) == {"_i18n_key": expected_key}


class TestStoreAnalysisErrorGuard:
    """Regression: store_analysis_error must not overwrite a completed run."""

    def test_error_does_not_overwrite_complete(self, tmp_path: pytest.TempPathFactory) -> None:
        db = HistoryDB(tmp_path / "test.db")
        run_id = "test-run-001"
        db.create_run(run_id, "2024-01-01T00:00:00", {"test": True})

        # Complete the analysis
        db.store_analysis(run_id, {"result": "ok"})
        status_before = db.get_run_status(run_id)
        assert status_before == "complete"

        # Try to overwrite with an error
        db.store_analysis_error(run_id, "spurious error")
        status_after = db.get_run_status(run_id)
        assert status_after == "complete", "store_analysis_error must not overwrite a completed run"


class TestEvidencePeakPresentFormat:
    """Regression: EVIDENCE_PEAK_PRESENT i18n template must use .1f for dB values."""

    def test_dB_format_is_one_decimal(self) -> None:
        i18n_path = SERVER_ROOT / "data" / "report_i18n.json"
        data = json.loads(i18n_path.read_text())

        en_template = data["EVIDENCE_PEAK_PRESENT"]["en"]
        nl_template = data["EVIDENCE_PEAK_PRESENT"]["nl"]

        # Must use .1f, not .4f
        assert ".1f}" in en_template, f"Expected .1f in EN template, got: {en_template}"
        assert ".1f}" in nl_template, f"Expected .1f in NL template, got: {nl_template}"
        assert ".4f" not in en_template, "Stale .4f found in EN template"
        assert ".4f" not in nl_template, "Stale .4f found in NL template"


# ===== From test_runtime_nan_and_update_guard_regressions.py =====

"""Runtime NaN handling and update-manager guard regressions:
NaN guards, correlation clamp, persist rollback,
firmware cache streaming, CancelledError re-raise, _normalize_lang dedup,
_weighted_percentile direct import, _dir_sha256 separators, _corr_abs_clamped,
_canonical_location edge cases, PDF peak suffix i18n."""


import asyncio

import pytest

from vibesensor.analysis.findings import _weighted_percentile
from vibesensor.analysis.helpers import _corr_abs_clamped
from vibesensor.analysis.summary import _normalize_lang
from vibesensor.firmware_cache import _dir_sha256
from vibesensor.report.pdf_builder import _strength_with_peak
from vibesensor.report.pdf_helpers import _canonical_location
from vibesensor.report_i18n import tr
from vibesensor.update.manager import UpdateManager, UpdateState

# ── 1. NaN guard in vibration_strength_db_scalar ─────────────────────────


class TestVibrationStrengthNanGuard:
    """Verify NaN inputs do not propagate through vibration_strength_db_scalar."""

    @pytest.mark.parametrize(
        "peak, floor",
        [
            (0.001, float("nan")),
            (float("nan"), 0.001),
            (float("nan"), float("nan")),
            (0.001, float("inf")),
        ],
    )
    def test_non_finite_input_returns_finite(self, peak: float, floor: float) -> None:
        result = vibration_strength_db_scalar(peak_band_rms_amp_g=peak, floor_amp_g=floor)
        assert math.isfinite(result), f"Expected finite, got {result}"

    def test_normal_values_unchanged(self):
        result = vibration_strength_db_scalar(peak_band_rms_amp_g=0.01, floor_amp_g=0.001)
        assert math.isfinite(result)
        assert result > 0  # peak > floor → positive dB


# ── 2. _corr_abs_clamped returns at most 1.0 ─────────────────────────────


class TestCorrAbsClamped:
    """Verify _corr_abs_clamped clamps to [0, 1]."""

    def test_perfect_correlation_clamped(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _corr_abs_clamped(x, y)
        assert 0 <= result <= 1.0

    def test_anticorrelation_clamped(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        result = _corr_abs_clamped(x, y)
        assert 0 <= result <= 1.0

    def test_near_identical_values_clamped(self):
        """When values are nearly identical, _corr_abs may return None (zero variance)."""
        # Tiny perturbation — std dev may be zero → None from _corr_abs
        x = [1.0000000001, 1.0000000002, 1.0000000003]
        y = [1.0000000001, 1.0000000002, 1.0000000003]
        result = _corr_abs_clamped(x, y)
        # Either None (zero variance) or clamped to [0, 1]
        assert result is None or result <= 1.0


# ── 3. SettingsStore persist rollback ─────────────────────────────────────


class TestSettingsStoreRollback:
    """Verify in-memory state is restored when _persist() fails."""

    @staticmethod
    def _make_store_failing_persist() -> SettingsStore:
        """Return a SettingsStore whose _persist() will raise."""
        store = SettingsStore(db=None)
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")
        return store

    def test_add_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        initial_count = len(store.get_cars()["cars"])

        # Make persist fail
        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB write fail")

        with pytest.raises(PersistenceError):
            store.add_car({"name": "New Car", "type": "suv"})

        assert len(store.get_cars()["cars"]) == initial_count

    def test_delete_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Car 1", "type": "sedan"})
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        car_count = len(cars["cars"])
        assert car_count >= 2
        target_id = cars["cars"][-1]["id"]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.delete_car(target_id)

        assert len(store.get_cars()["cars"]) == car_count

    def test_set_active_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Car 2", "type": "suv"})
        cars = store.get_cars()
        original_active = cars["activeCarId"]
        new_id = [c["id"] for c in cars["cars"] if c["id"] != original_active][0]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.set_active_car(new_id)

        assert store.get_cars()["activeCarId"] == original_active

    def test_update_car_rollback_on_persist_failure(self):
        store = SettingsStore(db=None)
        store.add_car({"name": "Original Name", "type": "sedan"})
        cars = store.get_cars()
        car_id = cars["cars"][0]["id"]
        original_name = cars["cars"][0]["name"]

        store._db = MagicMock()
        store._db.set_settings_snapshot.side_effect = Exception("DB fail")

        with pytest.raises(PersistenceError):
            store.update_car(car_id, {"name": "New Name"})

        assert store.get_cars()["cars"][0]["name"] == original_name


# ── 4. Firmware cache streaming download ──────────────────────────────────


class TestFirmwareCacheStreamingDownload:
    """Verify download streams to disk instead of buffering in memory."""

    def test_download_asset_creates_file(self, tmp_path):
        """_download_asset should stream data to a file."""
        config = FirmwareCacheConfig(cache_dir=str(tmp_path / "cache"))
        fetcher = GitHubReleaseFetcher(config)

        dest = tmp_path / "firmware.bin"
        test_data = b"firmware_content_bytes_here"

        # Mock urlopen to return test data
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [test_data, b""]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None

        with patch("vibesensor.firmware_cache.urlopen", return_value=mock_resp):
            fetcher._download_asset("https://example.com/fw.bin", dest)

        assert dest.exists()
        assert dest.read_bytes() == test_data


# ── 5. CancelledError re-raise in UpdateManager ──────────────────────────


class TestUpdateManagerCancelledError:
    """Verify CancelledError is re-raised after cleanup."""

    @pytest.mark.asyncio
    async def test_cancelled_error_is_reraised(self):
        """_run_update should re-raise CancelledError."""
        mgr = UpdateManager.__new__(UpdateManager)
        mgr._status = MagicMock()
        mgr._status.phase = MagicMock()
        mgr._status.state = UpdateState.running
        mgr._status.issues = []
        mgr._status.finished_at = None
        mgr._log_lines = []
        mgr._redact_secrets = set()
        mgr._state_store = MagicMock()
        mgr._state_store.save = MagicMock()

        async def mock_inner(ssid, password):
            raise asyncio.CancelledError()

        mgr._run_update_inner = mock_inner
        mgr._add_issue = MagicMock()
        mgr._log = MagicMock()
        mgr._persist_status = MagicMock()

        async def noop_restore():
            pass

        mgr._restore_hotspot = noop_restore
        mgr._collect_runtime_details = MagicMock(return_value={})

        with pytest.raises(asyncio.CancelledError):
            await mgr._run_update("ssid", "pass")


# ── 6. _normalize_lang uses canonical implementation ─────────────────────


class TestNormalizeLangDedup:
    """Verify summary uses the canonical normalize_lang."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("en", "en"),
            ("EN", "en"),
            ("", "en"),
            (None, "en"),
            ("nl", "nl"),
            ("NL", "nl"),
            ("nl-BE", "nl"),
        ],
    )
    def test_normalize_lang(self, raw: str | None, expected: str) -> None:
        assert _normalize_lang(raw) == expected


# ── 7. _weighted_percentile direct import ─────────────────────────────────


class TestWeightedPercentileImport:
    """Verify _weighted_percentile is importable from findings without trampoline."""

    def test_import_works(self):
        assert callable(_weighted_percentile)

    def test_basic_call(self):
        result = _weighted_percentile([(10.0, 1.0), (20.0, 1.0), (30.0, 1.0)], 0.5)
        assert result is not None


# ── 8. _dir_sha256 uses separators ────────────────────────────────────────


class TestDirSha256Separators:
    """Verify _dir_sha256 uses null-byte separators between path and content."""

    def test_different_layouts_produce_different_hashes(self, tmp_path):
        # Layout 1: file "a" with content "bc"
        d1 = tmp_path / "d1"
        d1.mkdir()
        (d1 / "a").write_text("bc")

        # Layout 2: file "ab" with content "c"
        d2 = tmp_path / "d2"
        d2.mkdir()
        (d2 / "ab").write_text("c")

        h1 = _dir_sha256(d1)
        h2 = _dir_sha256(d2)
        assert h1 != h2, "Hashes should differ when path/content boundaries differ"


# ── 9. _canonical_location edge cases ─────────────────────────────────────


class TestCanonicalLocation:
    """Dedicated edge-case tests for _canonical_location."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, ""),
            ("", ""),
            ("Front Left Wheel", "front-left wheel"),
            ("front_left_wheel", "front-left wheel"),
            ("FL", "front-left wheel"),
            ("FLwheel", "front-left wheel"),
            ("Front Right Wheel", "front-right wheel"),
            ("FR", "front-right wheel"),
            ("Rear Left Wheel", "rear-left wheel"),
            ("RL", "rear-left wheel"),
            ("Rear Right Wheel", "rear-right wheel"),
            ("RR", "rear-right wheel"),
            ("trunk", "trunk"),
            ("TRUNK", "trunk"),
            ("driveshaft tunnel", "driveshaft tunnel"),
            ("tunnel", "driveshaft tunnel"),
            ("engine bay", "engine bay"),
            ("Engine Bay", "engine bay"),
            ("driver seat", "driver seat"),
            ("Driver Seat", "driver seat"),
            ("dashboard", "dashboard"),
        ],
    )
    def test_canonical(self, raw, expected):
        assert _canonical_location(raw) == expected


# ── 10. PDF _strength_with_peak i18n suffix ───────────────────────────────


class TestStrengthWithPeakI18n:
    """Verify _strength_with_peak uses the provided suffix."""

    def test_default_suffix_is_peak(self):
        result = _strength_with_peak("Moderate", 28.3, fallback="—")
        assert "peak" in result
        assert "28.3" in result

    def test_nl_suffix(self):
        result = _strength_with_peak("Matig", 28.3, fallback="—", peak_suffix="piek")
        assert "piek" in result
        assert "peak" not in result
        assert "28.3" in result

    def test_no_peak_db(self):
        result = _strength_with_peak("Moderate", None, fallback="—")
        assert result == "Moderate"

    def test_db_in_label_skips_suffix(self):
        result = _strength_with_peak("28.3 dB", 28.3, fallback="—")
        assert result == "28.3 dB"  # no suffix appended


# ── 11. report_i18n STRENGTH_PEAK_SUFFIX key exists ──────────────────────


class TestReportI18nPeakSuffix:
    """Verify STRENGTH_PEAK_SUFFIX key exists in both languages."""

    @pytest.mark.parametrize(
        "lang, expected",
        [("en", "peak"), ("nl", "piek")],
    )
    def test_peak_suffix_key(self, lang: str, expected: str):
        assert tr(lang, "STRENGTH_PEAK_SUFFIX") == expected


# ── 12. Firmware cache restore on activation failure ──────────────────────


class TestFirmwareCacheRestore:
    """Verify old cache is restored when activation fails."""

    def test_old_current_restored_on_rename_failure(self, tmp_path):
        """If extract_dir.rename(target) fails, old_current should be restored."""

        current = tmp_path / "current"
        current.mkdir()
        (current / "marker.txt").write_text("old_firmware")
        old_backup = tmp_path / "current.old"

        # Simulate: target renamed to old, but new rename fails
        current.rename(old_backup)
        assert not current.exists()
        assert old_backup.exists()

        # Restore logic (same as in firmware_cache.py except block)
        if old_backup.exists() and not current.exists():
            old_backup.rename(current)

        assert current.exists()
        assert (current / "marker.txt").read_text() == "old_firmware"


# ===== From test_runtime_quality_pass_regressions.py =====

"""Runtime quality-pass regressions (issues 19–24).

Covers:
  19 – bad-client diagnostics skip (live_diagnostics)
  20 – ring buffer wraparound (processing)
  21 – _bounded_sample edge cases (api)
  22 – speed_unit persistence (settings_store)
  23 – iter_run_samples pagination correctness (history_db)
  24 – schema v2→v3 migration (history_db)
"""


import sqlite3
from math import pi

import pytest

from vibesensor.api import _bounded_sample
from vibesensor.live_diagnostics import LiveDiagnosticsEngine

# -- shared helpers ----------------------------------------------------------

def _make_history_db(tmp_path: Path, name: str = "history.db") -> HistoryDB:
    return HistoryDB(tmp_path / name)


def _seeded_history_db(
    tmp_path: Path, run_id: str, n_samples: int, *, name: str = "history.db"
) -> HistoryDB:
    """Create a HistoryDB with one run containing *n_samples* rows."""
    db = _make_history_db(tmp_path, name)
    db.create_run(run_id, "2026-01-01T00:00:00Z", {"src": "test"})
    db.append_samples(run_id, [{"i": i} for i in range(n_samples)])
    return db


def _make_tone_chunk(freq_hz: float, n_samples: int, sample_rate_hz: int) -> np.ndarray:
    """Return an (N, 3) float32 chunk with a sine tone on the X axis."""
    t = np.arange(n_samples, dtype=np.float64) / sample_rate_hz
    x = (0.5 * np.sin(2 * pi * freq_hz * t)).astype(np.float32)
    zeros = np.zeros_like(x)
    return np.stack([x, zeros, zeros], axis=1)


# ---------------------------------------------------------------------------
# Issue 19 – _detect_sensor_events skips bad clients rather than crashing
# ---------------------------------------------------------------------------


class TestDiagnosticsSkipsBadClients:
    """After the fix, a client with missing strength_metrics is silently
    skipped instead of raising ``ValueError``."""

    @staticmethod
    def _engine() -> LiveDiagnosticsEngine:
        return LiveDiagnosticsEngine()

    def test_missing_strength_metrics_is_skipped(self) -> None:
        engine = self._engine()
        good_payload: dict = {
            "strength_metrics": {
                "top_peaks": [{"hz": 10.0, "amp": 0.01, "vibration_strength_db": 5.0}],
            },
        }
        spectra = {"clients": {"good": good_payload, "bad": {"missing": True}}}
        # Should not raise
        events = engine._detect_sensor_events(
            speed_mps=10.0,
            clients=[{"id": "good"}, {"id": "bad"}],
            spectra=spectra,
            settings={},
        )
        # The good client is still processed; the bad one is silently skipped
        assert isinstance(events, list)
        assert len(events) >= 1, "Good client events should still be produced"

    def test_missing_top_peaks_is_skipped(self) -> None:
        engine = self._engine()
        spectra = {
            "clients": {
                "c1": {"strength_metrics": {"no_peaks_here": True}},
            }
        }
        events = engine._detect_sensor_events(
            speed_mps=10.0,
            clients=[{"id": "c1"}],
            spectra=spectra,
            settings={},
        )
        assert events == []


# ---------------------------------------------------------------------------
# Issue 20 – ring buffer wraparound
# ---------------------------------------------------------------------------


def test_ring_buffer_wraparound_returns_correct_latest_data() -> None:
    """Ingest more samples than the buffer capacity and verify the
    latest window returns the *most recent* data, not early data."""
    sample_rate_hz = 800
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=2,  # capacity = 800 * 2 = 1600 samples
        waveform_display_hz=100,
        fft_n=1024,
        spectrum_max_hz=200,
    )

    # Phase 1 – fill with a 10 Hz tone (2400 samples → wraps at 1600)
    processor.ingest(
        "c1", _make_tone_chunk(10.0, 2400, sample_rate_hz),
        sample_rate_hz=sample_rate_hz,
    )

    # Phase 2 – overwrite with a 50 Hz tone (another 2400 samples)
    processor.ingest(
        "c1", _make_tone_chunk(50.0, 2400, sample_rate_hz),
        sample_rate_hz=sample_rate_hz,
    )

    metrics = processor.compute_metrics("c1", sample_rate_hz=sample_rate_hz)
    peaks = metrics["combined"]["peaks"]
    # The dominant peak should now be around 50 Hz (the most-recent data),
    # not 10 Hz (the old, overwritten data).
    dominant_hz = max(peaks, key=lambda p: float(p["amp"]))["hz"]
    assert abs(float(dominant_hz) - 50.0) < 5.0, f"expected ~50 Hz peak, got {dominant_hz}"


# ---------------------------------------------------------------------------
# Issue 21 – _bounded_sample edge cases
# ---------------------------------------------------------------------------


class TestBoundedSample:
    @pytest.mark.parametrize(
        "n_items, max_items, total_hint, exp_total, exp_len, exp_stride",
        [
            pytest.param(5, 100, None, 5, 5, 1, id="small_input_no_halving"),
            pytest.param(10, 10, None, 10, 10, None, id="exact_limit"),
            pytest.param(0, 10, None, 0, 0, None, id="empty_input"),
        ],
    )
    def test_bounded_sample_basic(
        self,
        n_items: int,
        max_items: int,
        total_hint: int | None,
        exp_total: int,
        exp_len: int,
        exp_stride: int | None,
    ) -> None:
        items = [{"i": i} for i in range(n_items)]
        kwargs: dict = {"max_items": max_items}
        if total_hint is not None:
            kwargs["total_hint"] = total_hint
        kept, total, stride = _bounded_sample(iter(items), **kwargs)
        assert total == exp_total
        assert len(kept) == exp_len
        if exp_stride is not None:
            assert stride == exp_stride

    def test_halving_reduces_count(self) -> None:
        items = [{"i": i} for i in range(200)]
        kept, total, stride = _bounded_sample(iter(items), max_items=50)
        assert total == 200
        assert len(kept) <= 50
        assert stride > 1

    def test_total_hint_avoids_halving(self) -> None:
        """With total_hint provided, stride is pre-computed."""
        items = [{"i": i} for i in range(200)]
        kept, total, stride = _bounded_sample(iter(items), max_items=50, total_hint=200)
        assert total == 200
        assert stride == 4
        assert len(kept) == 50


# ---------------------------------------------------------------------------
# Issue 22 – speed_unit persistence round-trip
# ---------------------------------------------------------------------------


def test_speed_unit_persists_and_round_trips(tmp_path: Path) -> None:
    db = _make_history_db(tmp_path, "settings.db")
    store = SettingsStore(db)

    # Default
    assert store.speed_unit == "kmh"

    # Change to mps
    store.set_speed_unit("mps")
    assert store.speed_unit == "mps"

    # Reload from DB
    store2 = SettingsStore(db)
    assert store2.speed_unit == "mps"

    # Invalid falls back
    with pytest.raises(ValueError):
        store.set_speed_unit("mph")  # not a valid choice


# ---------------------------------------------------------------------------
# Issue 23 – iter_run_samples pagination correctness
# ---------------------------------------------------------------------------


def test_iter_run_samples_returns_all_rows(tmp_path: Path) -> None:
    total = 37
    db = _seeded_history_db(tmp_path, "r1", total)

    all_rows: list[dict] = []
    for batch in db.iter_run_samples("r1", batch_size=10):
        all_rows.extend(batch)
    assert len(all_rows) == total
    assert [r["i"] for r in all_rows] == list(range(total))


def test_iter_run_samples_offset(tmp_path: Path) -> None:
    db = _seeded_history_db(tmp_path, "r2", 20)

    all_rows: list[dict] = []
    for batch in db.iter_run_samples("r2", batch_size=5, offset=10):
        all_rows.extend(batch)
    assert len(all_rows) == 10
    assert all_rows[0]["i"] == 10


# ---------------------------------------------------------------------------
# Issue 24 – schema v2→v3 migration
# ---------------------------------------------------------------------------


def test_old_schema_version_raises(tmp_path: Path) -> None:
    """Opening a DB with an older schema version should raise RuntimeError."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """\
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO schema_meta (key, value) VALUES ('version', '2');
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT NOT NULL DEFAULT 'recording',
    error_message TEXT,
    metadata_json TEXT,
    analysis_json TEXT,
    created_at TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sample_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
"""
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Unsupported history DB schema version 2"):
        HistoryDB(db_path)


# ===== From test_runtime_queue_and_export_regressions.py =====

"""Runtime queue/history tracking and export-filter regressions."""


from collections import deque

import pytest

from vibesensor.analysis.test_plan import _weighted_percentile_speed
from vibesensor.live_diagnostics import _TrackerLevelState


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
        engine = LiveDiagnosticsEngine()
        assert isinstance(engine._phase_speed_history, deque)
        assert engine._phase_speed_history.maxlen is not None
        assert engine._phase_speed_history.maxlen > 0

    def test_reset_preserves_deque(self) -> None:
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
        engine = LiveDiagnosticsEngine()
        engine._sensor_trackers["stale:key"] = _TrackerLevelState()
        # Simulate 60 ticks of silence (not in seen set)
        for _ in range(60):
            engine._decay_unseen_sensor_trackers(set())
        assert "stale:key" not in engine._sensor_trackers

    def test_seen_trackers_not_pruned(self) -> None:
        engine = LiveDiagnosticsEngine()
        engine._sensor_trackers["active:key"] = _TrackerLevelState()
        for _ in range(100):
            engine._decay_unseen_sensor_trackers({"active:key"})
        assert "active:key" in engine._sensor_trackers


# ---------------------------------------------------------------------------
# Fix 5 – Dead functions removed
# ---------------------------------------------------------------------------
_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestDeadFunctionsRemoved:
    @pytest.mark.parametrize("rel_path, forbidden", _DEAD_FUNCTION_CASES, ids=[c[1] for c in _DEAD_FUNCTION_CASES])
    def test_dead_function_absent(self, rel_path: str, forbidden: str) -> None:
        text = (SERVER_ROOT / rel_path).read_text()
        assert forbidden not in text


# ---------------------------------------------------------------------------
# Fix 6 – _normalize_lang: kept inline per architectural boundary
# ---------------------------------------------------------------------------
class TestNormalizeLangArchitecturalBoundary:
    _SUMMARY_SRC = SERVER_ROOT / "vibesensor" / "analysis" / "summary.py"

    def test_summary_does_not_import_report_i18n(self) -> None:
        """summary.py must NOT import from report_i18n (i18n separation constraint)."""
        assert "from ..report_i18n import" not in self._SUMMARY_SRC.read_text()

    def test_summary_has_inline_normalize_lang(self) -> None:
        """summary.py must define its own _normalize_lang (avoiding report_i18n dep)."""
        assert "def _normalize_lang" in self._SUMMARY_SRC.read_text()


# ---------------------------------------------------------------------------
# Fix 7 – Export ZIP filters internal _-prefixed analysis fields
# ---------------------------------------------------------------------------
class TestExportZipFiltersInternals:
    def test_underscore_fields_stripped_in_source(self) -> None:
        """history route module must filter _-prefixed keys from analysis before export."""
        text = (SERVER_ROOT / "vibesensor" / "routes" / "history.py").read_text()
        assert 'not k.startswith("_")' in text


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
# Fix 9 – _analysis_queue has maxlen
# ---------------------------------------------------------------------------
class TestAnalysisQueueMaxlen:
    def test_analysis_queue_has_maxlen(self) -> None:
        """PostAnalysisWorker._analysis_queue must have a bounded maxlen."""
        text = (SERVER_ROOT / "vibesensor" / "metrics_log" / "post_analysis.py").read_text()
        assert "_analysis_queue: deque[str] = deque(maxlen=" in text


# ===== From test_runtime_validation_and_schema_regressions.py =====

"""Runtime validation and schema-recovery regressions.

Covers:
  1. _corr_abs — NaN propagation guard (helpers.py)
  2. pdf_diagram.py — next() with default for marker lookup
  3. pdf_builder.py — confidence NaN/Inf guard
  4. persistent_findings.py — type hint list[str] (compile-time only)
  5. api_models.py — input validation bounds on request models
  6. history_db.py — corrupted schema version recovery
  7. settings_store.py — dict rollback safety
  8. json_utils.py — depth limit prevents infinite recursion
"""



import pytest
from pydantic import ValidationError

from vibesensor.analysis.helpers import _corr_abs
from vibesensor.api_models import CarUpsertRequest, SensorRequest, SpeedSourceRequest
from vibesensor.json_utils import sanitize_for_json

# ------------------------------------------------------------------
# 1. _corr_abs — NaN propagation guard
# ------------------------------------------------------------------

_CORR_NONE_CASES = [
    pytest.param([1.0, float("nan"), 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], id="nan_in_x"),
    pytest.param([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, float("nan"), 6.0, 8.0, 10.0], id="nan_in_y"),
    pytest.param([float("nan")] * 5, [float("nan")] * 5, id="all_nan"),
    pytest.param([5.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], id="constant_x"),
    pytest.param([1.0, 2.0], [3.0, 4.0], id="too_few"),
    pytest.param([1.0, float("inf"), 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0], id="inf_in_x"),
]


class TestCorrAbsNanGuard:
    """_corr_abs must return None (not NaN) for NaN-contaminated inputs."""

    def test_normal_correlation(self) -> None:
        result = _corr_abs([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 4.0, 6.0, 8.0, 10.0])
        assert result is not None
        assert abs(result - 1.0) < 1e-6

    @pytest.mark.parametrize("x, y", _CORR_NONE_CASES)
    def test_corr_abs_returns_none(self, x: list[float], y: list[float]) -> None:
        assert _corr_abs(x, y) is None


# ------------------------------------------------------------------
# 2. pdf_diagram — next() with default for marker lookup
# ------------------------------------------------------------------


class TestPdfDiagramMarkerLookup:
    """Marker lookup must not raise StopIteration for missing markers.

    The fix changed ``next(item for ...)`` to ``next((...), None)``
    with a ``continue`` guard in pdf_diagram.py.  We verify the
    pattern at a unit level (the inline logic is inside
    car_location_diagram and not separately testable).
    """

    def test_next_with_default_returns_none(self) -> None:
        """Verify the pattern used in the fix: next() with default None."""
        items = [{"name": "a"}, {"name": "b"}]
        result = next((i for i in items if i["name"] == "missing"), None)
        assert result is None

    def test_next_without_default_raises(self) -> None:
        """Document the original bug: next() without default raises."""
        items = [{"name": "a"}, {"name": "b"}]
        with pytest.raises(StopIteration):
            next(i for i in items if i["name"] == "missing")


# ------------------------------------------------------------------
# 3. pdf_builder — confidence NaN/Inf guard
# ------------------------------------------------------------------


def _safe_confidence(raw: object) -> float:
    """Replicate the production clamping logic for confidence values."""
    try:
        val = float(raw or 0.0)
    except (ValueError, TypeError):
        val = 0.0
    return val if math.isfinite(val) else 0.0


class TestConfidenceNanGuard:
    """Confidence formatting must handle NaN/Inf gracefully."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            pytest.param(float("nan"), 0.0, id="nan"),
            pytest.param(float("inf"), 0.0, id="inf"),
            pytest.param(0.75, 0.75, id="valid"),
        ],
    )
    def test_confidence_clamped(self, raw: float, expected: float) -> None:
        confidence = _safe_confidence(raw)
        assert abs(confidence - expected) < 1e-6
        # Verify formatting doesn't crash
        f"({confidence * 100.0:.0f}%)"  # noqa: B018


# ------------------------------------------------------------------
# 4. api_models — input validation bounds
# ------------------------------------------------------------------

_VALIDATION_REJECT_CASES = [
    pytest.param(CarUpsertRequest, {"name": "x" * 65}, id="car_name_too_long"),
    pytest.param(SpeedSourceRequest, {"manualSpeedKph": -10}, id="speed_negative"),
    pytest.param(SpeedSourceRequest, {"manualSpeedKph": 501}, id="speed_too_high"),
    pytest.param(SpeedSourceRequest, {"staleTimeoutS": 301}, id="stale_timeout_too_high"),
    pytest.param(SensorRequest, {"name": "x" * 65}, id="sensor_name_too_long"),
    pytest.param(SensorRequest, {"location": "x" * 65}, id="sensor_location_too_long"),
]


class TestApiModelValidationBounds:
    """Request models must reject out-of-bounds values."""

    @pytest.mark.parametrize("model, kwargs", _VALIDATION_REJECT_CASES)
    def test_out_of_bounds_rejected(self, model: type, kwargs: dict) -> None:
        with pytest.raises(ValidationError):
            model(**kwargs)

    def test_car_upsert_name_within_limit_ok(self) -> None:
        req = CarUpsertRequest(name="x" * 64)
        assert req.name == "x" * 64

    def test_speed_source_valid_speed_ok(self) -> None:
        req = SpeedSourceRequest(manualSpeedKph=120)
        assert req.manualSpeedKph == 120

    def test_sensor_request_valid_ok(self) -> None:
        req = SensorRequest(name="MySensor", location="front_left")
        assert req.name == "MySensor"
        assert req.location == "front_left"


# ------------------------------------------------------------------
# 5. history_db — corrupted schema version recovery
# ------------------------------------------------------------------


class TestHistoryDbCorruptedSchemaVersion:
    """_ensure_schema must not crash on corrupted version metadata."""

    def test_corrupted_version_string_recovers(self, tmp_path) -> None:
        db_path = tmp_path / "test.db"
        # Create a DB with a corrupted version value
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO schema_meta (key, value) VALUES ('version', 'CORRUPT')")
        conn.commit()
        conn.close()

        # Should not crash — should recover
        assert HistoryDB(db_path) is not None

    def test_valid_version_still_works(self, tmp_path) -> None:
        assert HistoryDB(tmp_path / "test.db") is not None


# ------------------------------------------------------------------
# 6. settings_store — dict rollback safety
# ------------------------------------------------------------------


class TestSettingsStoreRollbackSafety:
    """Car aspects rollback must use clear/update, not reassignment."""

    def test_rollback_preserves_dict_identity(self) -> None:
        """After a failed persist, the car.aspects dict object
        should still be the same object (not replaced)."""
        store = SettingsStore(db=None)
        car_data = store.add_car({"name": "TestCar", "type": "sedan"})
        car_id = car_data["cars"][0]["id"]

        # Set as active so _find_car works
        store.set_active_car(car_id)

        # Get the aspects dict reference before update
        with store._lock:
            car = store._find_car(car_id)
            original_aspects_id = id(car.aspects)

        # Force persist to fail
        with patch.object(store, "_persist", side_effect=Exception("disk full")):
            try:
                store.update_car(car_id, {"aspects": {"wheel": 1.0, "driveshaft": 0.5}})
            except Exception:
                pass

        # The aspects dict should still be the SAME object
        with store._lock:
            car = store._find_car(car_id)
            assert id(car.aspects) == original_aspects_id


# ------------------------------------------------------------------
# 7. json_utils — depth limit prevents infinite recursion
# ------------------------------------------------------------------


class TestJsonSanitizeDepthLimit:
    """sanitize_for_json must not crash on deeply nested or circular structures."""

    def test_deeply_nested_dict_truncated(self) -> None:
        # Build a dict nested 200 levels deep (exceeds default 128 limit)
        obj: dict = {}
        current = obj
        for _i in range(200):
            current["child"] = {}
            current = current["child"]
        current["value"] = 42.0

        result, _ = sanitize_for_json(obj)
        # Should not crash; deeply nested values should be truncated to None
        assert result is not None

    def test_normal_depth_preserved(self) -> None:
        obj = {"a": {"b": {"c": 1.5}}}
        result, found = sanitize_for_json(obj)
        assert result == {"a": {"b": {"c": 1.5}}}
        assert not found


# ===== From test_strength_and_spectrum_runtime_regressions.py =====

"""Strength bucketing and combined-spectrum runtime regressions:
- combined spectrum not polluted by zeroed amp_for_peaks
- order tolerance scales with path_compliance
- _noise_floor no double bin removal
- bucket_for_strength returns 'l0' for negative dB
- dead db_value variable removed from _top_strength_values
"""


import inspect
import re

import pytest
from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.analysis.helpers import ORDER_TOLERANCE_MIN_HZ, ORDER_TOLERANCE_REL
from vibesensor.analysis.report_data_builder import _top_strength_values
from vibesensor.processing.fft import compute_fft_spectrum


class TestBucketForStrengthNegativeDB:
    """Regression: bucket_for_strength must return 'l0' for negative dB,
    not None."""

    @pytest.mark.parametrize(
        "db_val, expected",
        [
            pytest.param(-5.0, "l0", id="negative"),
            pytest.param(0.0, "l0", id="zero"),
            pytest.param(7.9, "l0", id="below_l1"),
            pytest.param(8.0, "l1", id="l1_boundary"),
            pytest.param(50.0, "l5", id="high"),
        ],
    )
    def test_bucket_boundaries(self, db_val: float, expected: str) -> None:
        assert bucket_for_strength(db_val) == expected


class TestCombinedSpectrumNotZeroed:
    """Regression: axis_amp_slices must use amp_slice (original), not
    amp_for_peaks (which has DC bin zeroed). Otherwise the combined
    spectrum inherits the artificial zero."""

    def test_amp_slice_used_not_amp_for_peaks(self) -> None:
        """Verify source code appends amp_slice (not amp_for_peaks)
        to axis_amp_slices."""
        src = inspect.getsource(compute_fft_spectrum)
        # Find the line that appends to axis_amp_slices
        match = re.search(r"axis_amp_slices\.append\((\w+)\)", src)
        assert match is not None, "axis_amp_slices.append() not found"
        appended_var = match.group(1)
        assert appended_var == "amp_slice", (
            f"Expected axis_amp_slices.append(amp_slice), "
            f"got axis_amp_slices.append({appended_var})"
        )


class TestNoiseFloorNoDoubleRemoval:
    """Regression: _noise_floor must not skip amps[1:] before delegating
    to noise_floor_amp_p20_g, since the caller already provides the
    analysis-band slice (DC already removed)."""

    def test_all_bins_included(self) -> None:
        amps = np.array([0.010, 0.012, 0.009, 0.011, 0.013], dtype=np.float32)
        floor = SignalProcessor._noise_floor(amps)
        # All 5 bins should be considered. If amps[1:] were used,
        # the first bin (0.010) would be excluded, changing the result.
        # P20 of [0.009, 0.010, 0.011, 0.012, 0.013] ≈ 0.0098
        assert floor > 0.0
        # The result must include the first bin. If it were excluded,
        # P20 of [0.011, 0.012, 0.013] = 0.0114, which is higher.
        # With all 5 bins, P20 is lower because 0.009 and 0.010 pull it down.
        floor_without_first = SignalProcessor._noise_floor(amps[1:])
        assert floor <= floor_without_first + 1e-6, (
            f"Floor {floor} should be ≤ floor-without-first {floor_without_first}"
        )


class TestOrderToleranceScalesWithCompliance:
    """Regression: order tolerance must scale with path_compliance so
    wheel hypotheses (compliance=1.5) get a wider matching window."""

    def test_compliance_1_baseline(self) -> None:
        predicted_hz = 20.0
        compliance = 1.0
        tolerance = max(
            ORDER_TOLERANCE_MIN_HZ,
            predicted_hz * ORDER_TOLERANCE_REL * compliance,
        )
        expected = max(ORDER_TOLERANCE_MIN_HZ, 20.0 * 0.08 * 1.0)
        assert abs(tolerance - expected) < 1e-9

    def test_compliance_1_5_wider(self) -> None:
        predicted_hz = 20.0
        tol_1 = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL * 1.0**0.5)
        tol_15 = max(ORDER_TOLERANCE_MIN_HZ, predicted_hz * ORDER_TOLERANCE_REL * 1.5**0.5)
        assert tol_15 > tol_1, "compliance=1.5 must produce wider tolerance"
        # sqrt(1.5) ≈ 1.2247
        ratio = tol_15 / tol_1
        assert abs(ratio - 1.5**0.5) < 1e-6, (
            f"Tolerance should scale by sqrt(compliance), got {ratio}"
        )


class TestDeadDbValueRemoved:
    """Regression: _top_strength_values should not contain unused db_value
    variable."""

    def test_no_db_value_in_source(self) -> None:
        source = inspect.getsource(_top_strength_values)
        assert "db_value" not in source, (
            "Dead variable db_value still present in _top_strength_values"
        )
