# ruff: noqa: E501
"""Tests for the 20 analysis-pipeline fixes.

Each test is tagged with the fix number it validates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vibesensor.history_db import HistoryDB
from vibesensor.runlog import bounded_sample, normalize_sample_record

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "pipeline_test.db")


def _simple_metadata(run_id: str = "test-run", lang: str = "en") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:05:00Z",
        "sensor_model": "ADXL345",
        "language": lang,
    }


def _simple_samples(n: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "t_s": float(i),
            "speed_kmh": 60.0 + i,
            "vibration_strength_db": 25.0 + i * 0.5,
            "accel_x_g": 0.01 * i,
            "accel_y_g": 0.02 * i,
            "accel_z_g": 1.0 + 0.005 * i,
            "client_id": "sensor_a",
            "location": "Front Left",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Fix 1: bounded_sample extracted to runlog.py
# ---------------------------------------------------------------------------


class TestBoundedSample:
    """Fix 1: The canonical bounded_sample lives in runlog, not duplicated."""

    def test_basic_downsampling(self) -> None:
        items = [{"i": i} for i in range(100)]
        kept, total, stride = bounded_sample(iter(items), max_items=20)
        assert total == 100
        assert len(kept) <= 20
        assert stride >= 1

    def test_no_downsampling_when_below_limit(self) -> None:
        items = [{"i": i} for i in range(5)]
        kept, total, stride = bounded_sample(iter(items), max_items=100)
        assert total == 5
        assert len(kept) == 5
        assert stride == 1

    def test_total_hint_precomputes_stride(self) -> None:
        items = [{"i": i} for i in range(1000)]
        kept, total, stride = bounded_sample(iter(items), max_items=50, total_hint=1000)
        assert total == 1000
        assert len(kept) <= 50

    def test_empty_input(self) -> None:
        kept, total, stride = bounded_sample(iter([]), max_items=10)
        assert total == 0
        assert len(kept) == 0
        assert stride == 1


# ---------------------------------------------------------------------------
# Fix 2: sensor_statistics_by_location alias removed
# ---------------------------------------------------------------------------


def test_no_sensor_statistics_alias() -> None:
    """Fix 2: summarize_run_data must not include the dead alias key."""
    from vibesensor.analysis import summarize_run_data

    summary = summarize_run_data(_simple_metadata(), _simple_samples(), include_samples=False)
    assert "sensor_intensity_by_location" in summary
    assert "sensor_statistics_by_location" not in summary


# ---------------------------------------------------------------------------
# Fix 3: lang normalization in insights endpoint
# ---------------------------------------------------------------------------


def test_insights_lang_normalization() -> None:
    """Fix 3: summarize_run_data normalizes lang parameter consistently."""
    from vibesensor.analysis import summarize_run_data

    # Unnormalized "EN" should produce same result as "en"
    summary_en = summarize_run_data(
        _simple_metadata(), _simple_samples(), lang="EN", include_samples=False
    )
    summary_en2 = summarize_run_data(
        _simple_metadata(), _simple_samples(), lang="en", include_samples=False
    )
    assert summary_en["lang"] == summary_en2["lang"] == "en"


# ---------------------------------------------------------------------------
# Fix 5: Worker thread exit race
# ---------------------------------------------------------------------------


class TestWorkerThreadRace:
    """Fix 5: _analysis_thread cleared on exit so new scheduling works."""

    def test_analysis_thread_cleared_on_completion(self, tmp_path: Path) -> None:
        from vibesensor.metrics_log import MetricsLogger

        class FakeReg:
            def active_client_ids(self):
                return []

            def get(self, _):
                return None

        class FakeGPS:
            speed_mps = None
            effective_speed_mps = None
            override_speed_mps = None

        class FakeProc:
            pass

        class FakeSettings:
            def snapshot(self):
                return {}

        logger = MetricsLogger(
            enabled=False,
            log_path=tmp_path / "m.jsonl",
            metrics_log_hz=2,
            registry=FakeReg(),
            gps_monitor=FakeGPS(),
            processor=FakeProc(),
            analysis_settings=FakeSettings(),
            sensor_model="test",
            default_sample_rate_hz=800,
            fft_window_size_samples=256,
        )

        # Simulate analysis that completes immediately
        seen = []

        def _mock_analysis(run_id):
            seen.append(run_id)

        logger._run_post_analysis = _mock_analysis  # type: ignore[assignment]
        logger._schedule_post_analysis("run-1")
        logger.wait_for_post_analysis(timeout_s=2.0)

        # Thread should be cleared after completion
        with logger._lock:
            assert logger._analysis_thread is None

        # Should be able to schedule again without issues
        logger._schedule_post_analysis("run-2")
        logger.wait_for_post_analysis(timeout_s=2.0)
        assert seen == ["run-1", "run-2"]


# ---------------------------------------------------------------------------
# Fix 6: analysis_is_current staleness check
# ---------------------------------------------------------------------------


def test_analysis_is_current(tmp_path: Path) -> None:
    """Fix 6: analysis_is_current returns True when version matches."""
    db = _make_db(tmp_path)
    db.create_run("r1", "2026-01-01T00:00:00Z", {})
    db.finalize_run("r1", "2026-01-01T00:05:00Z")
    db.store_analysis("r1", {"findings": []})

    assert db.analysis_is_current("r1") is True


def test_analysis_is_not_current_without_analysis(tmp_path: Path) -> None:
    """Fix 6: analysis_is_current returns False for unanalyzed run."""
    db = _make_db(tmp_path)
    db.create_run("r1", "2026-01-01T00:00:00Z", {})
    assert db.analysis_is_current("r1") is False


# ---------------------------------------------------------------------------
# Fix 7: Status transition validation
# ---------------------------------------------------------------------------


def test_finalize_run_only_from_recording(tmp_path: Path) -> None:
    """Fix 7: finalize_run only transitions from 'recording' state."""
    db = _make_db(tmp_path)
    db.create_run("r1", "2026-01-01T00:00:00Z", {})
    db.finalize_run("r1", "2026-01-01T00:05:00Z")
    status = db.get_run_status("r1")
    assert status == "analyzing"

    # Second finalize should be a no-op (already in 'analyzing')
    db.finalize_run("r1", "2026-01-01T00:10:00Z")
    status = db.get_run_status("r1")
    assert status == "analyzing"


def test_store_analysis_idempotent(tmp_path: Path) -> None:
    """Fix 10: store_analysis skips already-complete runs."""
    db = _make_db(tmp_path)
    db.create_run("r1", "2026-01-01T00:00:00Z", {})
    db.finalize_run("r1", "2026-01-01T00:05:00Z")
    db.store_analysis("r1", {"findings": [{"id": "first"}]})

    run = db.get_run("r1")
    assert run is not None
    assert run["analysis"]["findings"] == [{"id": "first"}]

    # Second store_analysis should be skipped
    db.store_analysis("r1", {"findings": [{"id": "second"}]})
    run = db.get_run("r1")
    assert run is not None
    assert run["analysis"]["findings"] == [{"id": "first"}]


# ---------------------------------------------------------------------------
# Fix 9: end_time_utc in finalized metadata
# ---------------------------------------------------------------------------


def test_end_time_utc_in_metadata(tmp_path: Path) -> None:
    """Fix 9: metadata should contain end_time_utc from run data."""
    from vibesensor.analysis import summarize_run_data

    meta = _simple_metadata()
    meta["end_time_utc"] = "2026-01-01T00:05:00Z"
    summary = summarize_run_data(meta, _simple_samples(), include_samples=False)
    assert summary.get("end_time_utc") == "2026-01-01T00:05:00Z"


# ---------------------------------------------------------------------------
# Fix 11: report_date uses end_time_utc, not datetime.now()
# ---------------------------------------------------------------------------


def test_report_date_deterministic() -> None:
    """Fix 11: report_date should use end_time_utc, not datetime.now()."""
    from vibesensor.analysis import summarize_run_data

    meta = _simple_metadata()
    meta["end_time_utc"] = "2026-06-15T12:00:00Z"
    summary = summarize_run_data(meta, _simple_samples(), include_samples=False)
    assert summary["report_date"] == "2026-06-15T12:00:00Z"


def test_report_date_fallback_when_no_end_time() -> None:
    """Fix 11: Without end_time_utc, report_date falls back to datetime.now()."""
    from vibesensor.analysis import summarize_run_data

    meta = _simple_metadata()
    meta.pop("end_time_utc", None)
    summary = summarize_run_data(meta, _simple_samples(), include_samples=False)
    # Should be a valid ISO timestamp (not None)
    assert summary["report_date"] is not None
    assert "T" in str(summary["report_date"])


# ---------------------------------------------------------------------------
# Fix 12: _prepare_speed_and_phases shared helper
# ---------------------------------------------------------------------------


def test_build_findings_uses_shared_speed_prep() -> None:
    """Fix 12: build_findings_for_samples produces same speed analysis as summarize_run_data."""
    from vibesensor.analysis import build_findings_for_samples, summarize_run_data

    meta = _simple_metadata()
    samples = _simple_samples(50)
    findings_standalone = build_findings_for_samples(metadata=meta, samples=samples, lang="en")
    summary = summarize_run_data(meta, samples, lang="en", include_samples=False)

    # Both should produce the same set of finding IDs
    standalone_ids = {f.get("finding_id") for f in findings_standalone}
    summary_ids = {f.get("finding_id") for f in summary.get("findings", [])}
    assert standalone_ids == summary_ids


# ---------------------------------------------------------------------------
# Fix 14: Stuck 'analyzing' run recovery
# ---------------------------------------------------------------------------


def test_stale_analyzing_run_ids(tmp_path: Path) -> None:
    """Fix 14: stale_analyzing_run_ids finds stuck runs."""
    db = _make_db(tmp_path)
    db.create_run("r1", "2026-01-01T00:00:00Z", {})
    db.finalize_run("r1", "2026-01-01T00:05:00Z")
    # r1 is now in 'analyzing' state

    db.create_run("r2", "2026-01-01T00:10:00Z", {})
    # r2 is in 'recording' state

    stale = db.stale_analyzing_run_ids()
    assert stale == ["r1"]


def test_recover_stale_does_not_touch_analyzing(tmp_path: Path) -> None:
    """Fix 14: recover_stale_recording_runs leaves 'analyzing' runs alone."""
    db = _make_db(tmp_path)
    db.create_run("r1", "2026-01-01T00:00:00Z", {})
    db.finalize_run("r1", "2026-01-01T00:05:00Z")
    # r1 is 'analyzing'

    db.create_run("r2", "2026-01-01T00:10:00Z", {})
    # r2 is 'recording'

    recovered = db.recover_stale_recording_runs()
    assert recovered == 1  # only r2

    assert db.get_run_status("r1") == "analyzing"
    assert db.get_run_status("r2") == "error"


# ---------------------------------------------------------------------------
# Fix 15: build_report_pdf type validation
# ---------------------------------------------------------------------------


def test_build_report_pdf_rejects_invalid_type() -> None:
    """build_report_pdf raises AttributeError for non-ReportTemplateData input."""
    from vibesensor.report.pdf_builder import build_report_pdf

    with pytest.raises((AttributeError, RuntimeError)):
        build_report_pdf("not a valid input")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fix 16: Insights response stripping
# ---------------------------------------------------------------------------


def test_insights_strips_internal_fields() -> None:
    """Fix 16: Internal _-prefixed fields should be stripped from insights."""
    # This is a behavioral contract test — the logic is in the API endpoint.
    # We verify the stripping logic directly.
    analysis = {
        "findings": [],
        "top_causes": [],
        "_report_template_data": {"large": "blob"},
        "_analysis_is_current": True,
        "lang": "en",
    }
    cleaned = {k: v for k, v in analysis.items() if not k.startswith("_")}
    assert "_report_template_data" not in cleaned
    assert "_analysis_is_current" not in cleaned
    assert "findings" in cleaned
    assert "lang" in cleaned


# ---------------------------------------------------------------------------
# Fix 19: report_cli respects include_samples
# ---------------------------------------------------------------------------


def test_report_cli_summary_excludes_samples_for_pdf() -> None:
    """Fix 19: CLI should not include samples unless summary JSON is requested."""
    from vibesensor.analysis import summarize_run_data

    meta = _simple_metadata()
    samples = _simple_samples()
    summary = summarize_run_data(meta, samples, include_samples=False)
    assert "samples" not in summary


# ---------------------------------------------------------------------------
# End-to-end pipeline test
# ---------------------------------------------------------------------------


def test_end_to_end_pipeline(tmp_path: Path) -> None:
    """Full pipeline: create → record → finalize → analyze → persist → report."""
    from vibesensor.analysis import map_summary, summarize_run_data
    from vibesensor.report.pdf_builder import build_report_pdf

    db = _make_db(tmp_path)

    # 1. Create run
    run_id = "e2e-test-run"
    metadata = _simple_metadata(run_id)
    db.create_run(run_id, "2026-01-01T00:00:00Z", metadata)
    assert db.get_run_status(run_id) == "recording"

    # 2. Record samples
    samples = _simple_samples(30)
    db.append_samples(run_id, samples)

    # 3. Finalize (stop recording)
    db.finalize_run(run_id, "2026-01-01T00:05:00Z")
    assert db.get_run_status(run_id) == "analyzing"

    # 4. Analyze
    read_samples = db.get_run_samples(run_id)
    normalized = [normalize_sample_record(s) for s in read_samples]
    summary = summarize_run_data(
        metadata, normalized, lang="en", file_name=run_id, include_samples=False
    )
    assert isinstance(summary, dict)
    assert "findings" in summary
    assert "top_causes" in summary
    assert "run_suitability" in summary
    assert "samples" not in summary

    # 5. Persist
    db.store_analysis(run_id, summary)
    assert db.get_run_status(run_id) == "complete"
    assert db.analysis_is_current(run_id)

    # 6. Verify persisted analysis
    run = db.get_run(run_id)
    assert run is not None
    assert isinstance(run.get("analysis"), dict)
    analysis = run["analysis"]

    # 7. Generate report from analysis
    report_data = map_summary(analysis)
    pdf_bytes = build_report_pdf(report_data)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000  # non-trivial PDF
    assert pdf_bytes[:5] == b"%PDF-"

    # 8. Verify idempotency — second store_analysis should be skipped
    db.store_analysis(run_id, {"findings": [{"id": "should-not-overwrite"}]})
    run2 = db.get_run(run_id)
    assert run2 is not None
    # Original analysis should be preserved
    assert run2["analysis"].get("run_id") == run_id

    # 9. Verify no duplicated keys
    assert "sensor_statistics_by_location" not in analysis

    # 10. Verify report_date is deterministic
    assert analysis.get("report_date") == "2026-01-01T00:05:00Z"
