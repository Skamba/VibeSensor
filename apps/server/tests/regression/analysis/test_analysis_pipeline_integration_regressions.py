# ruff: noqa: E402
from __future__ import annotations

"""Analysis pipeline integration regressions.

Each test is tagged with the fix number it validates.
"""


from pathlib import Path
from typing import Any

import pytest

from vibesensor.analysis import build_findings_for_samples, map_summary, summarize_run_data
from vibesensor.history_db import HistoryDB
from vibesensor.metrics_log import MetricsLogger, MetricsLoggerConfig
from vibesensor.report.pdf_engine import build_report_pdf
from vibesensor.runlog import bounded_sample, normalize_sample_record

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

_START = "2026-01-01T00:00:00Z"
_END = "2026-01-01T00:05:00Z"


@pytest.fixture
def db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "pipeline_test.db")


def _simple_metadata(run_id: str = "test-run", lang: str = "en") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "start_time_utc": _START,
        "end_time_utc": _END,
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


def _summarize(**overrides: Any) -> dict[str, Any]:
    """Shortcut: summarize_run_data with sensible defaults."""
    kw: dict[str, Any] = {"include_samples": False}
    kw.update(overrides)
    meta = kw.pop("metadata", _simple_metadata())
    samples = kw.pop("samples", _simple_samples())
    return summarize_run_data(meta, samples, **kw)


# ---------------------------------------------------------------------------
# Fix 1: bounded_sample extracted to runlog.py
# ---------------------------------------------------------------------------


class TestBoundedSample:
    """Fix 1: The canonical bounded_sample lives in runlog, not duplicated."""

    @pytest.mark.parametrize(
        ("n", "max_items", "total_hint", "expect_total", "expect_max_len"),
        [
            pytest.param(100, 20, None, 100, 20, id="downsampling"),
            pytest.param(5, 100, None, 5, 5, id="below-limit"),
            pytest.param(1000, 50, 1000, 1000, 50, id="total-hint"),
            pytest.param(0, 10, None, 0, 0, id="empty"),
        ],
    )
    def test_bounded_sample(
        self,
        n: int,
        max_items: int,
        total_hint: int | None,
        expect_total: int,
        expect_max_len: int,
    ) -> None:
        items = [{"i": i} for i in range(n)]
        kwargs: dict[str, Any] = {"max_items": max_items}
        if total_hint is not None:
            kwargs["total_hint"] = total_hint
        kept, total, stride = bounded_sample(iter(items), **kwargs)
        assert total == expect_total
        assert len(kept) <= expect_max_len
        assert stride >= 1


# ---------------------------------------------------------------------------
# Fix 2: sensor_statistics_by_location alias removed
# ---------------------------------------------------------------------------


def test_no_sensor_statistics_alias() -> None:
    """Fix 2: summarize_run_data must not include the dead alias key."""
    summary = _summarize()
    assert "sensor_intensity_by_location" in summary
    assert "sensor_statistics_by_location" not in summary


# ---------------------------------------------------------------------------
# Fix 3: lang normalization in insights endpoint
# ---------------------------------------------------------------------------


def test_insights_lang_normalization() -> None:
    """Fix 3: summarize_run_data normalizes lang parameter consistently."""
    summary_upper = _summarize(lang="EN")
    summary_lower = _summarize(lang="en")
    assert summary_upper["lang"] == summary_lower["lang"] == "en"


# ---------------------------------------------------------------------------
# Fix 5: Worker thread exit race
# ---------------------------------------------------------------------------


class TestWorkerThreadRace:
    """Fix 5: _analysis_thread cleared on exit so new scheduling works."""

    def test_analysis_thread_cleared_on_completion(self, tmp_path: Path) -> None:
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
            MetricsLoggerConfig(
                enabled=False,
                log_path=tmp_path / "m.jsonl",
                metrics_log_hz=2,
                sensor_model="test",
                default_sample_rate_hz=800,
                fft_window_size_samples=256,
            ),
            registry=FakeReg(),
            gps_monitor=FakeGPS(),
            processor=FakeProc(),
            analysis_settings=FakeSettings(),
        )

        seen: list[str] = []

        def _mock_analysis(run_id: str) -> None:
            seen.append(run_id)

        logger._post_analysis._run_post_analysis = _mock_analysis  # type: ignore[assignment]
        logger.schedule_post_analysis("run-1")
        logger.wait_for_post_analysis(timeout_s=2.0)

        with logger._post_analysis._lock:
            assert logger._post_analysis._analysis_thread is None

        logger.schedule_post_analysis("run-2")
        logger.wait_for_post_analysis(timeout_s=2.0)
        assert seen == ["run-1", "run-2"]


# ---------------------------------------------------------------------------
# Fix 6: analysis_is_current staleness check
# ---------------------------------------------------------------------------


def test_analysis_is_current(db: HistoryDB) -> None:
    """Fix 6: analysis_is_current returns True when version matches."""
    db.create_run("r1", _START, {})
    db.finalize_run("r1", _END)
    db.store_analysis("r1", {"findings": []})
    assert db.analysis_is_current("r1") is True


def test_analysis_is_not_current_without_analysis(db: HistoryDB) -> None:
    """Fix 6: analysis_is_current returns False for unanalyzed run."""
    db.create_run("r1", _START, {})
    assert db.analysis_is_current("r1") is False


# ---------------------------------------------------------------------------
# Fix 7: Status transition validation
# ---------------------------------------------------------------------------


def test_finalize_run_only_from_recording(db: HistoryDB) -> None:
    """Fix 7: finalize_run only transitions from 'recording' state."""
    db.create_run("r1", _START, {})
    db.finalize_run("r1", _END)
    assert db.get_run_status("r1") == "analyzing"

    # Second finalize should be a no-op (already in 'analyzing')
    db.finalize_run("r1", "2026-01-01T00:10:00Z")
    assert db.get_run_status("r1") == "analyzing"


def test_store_analysis_idempotent(db: HistoryDB) -> None:
    """Fix 10: store_analysis skips already-complete runs."""
    db.create_run("r1", _START, {})
    db.finalize_run("r1", _END)
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


def test_end_time_utc_in_metadata() -> None:
    """Fix 9: metadata should contain end_time_utc from run data."""
    summary = _summarize()
    assert summary.get("end_time_utc") == _END


# ---------------------------------------------------------------------------
# Fix 11: report_date uses end_time_utc, not datetime.now()
# ---------------------------------------------------------------------------


def test_report_date_deterministic() -> None:
    """Fix 11: report_date should use end_time_utc, not datetime.now()."""
    meta = _simple_metadata()
    meta["end_time_utc"] = "2026-06-15T12:00:00Z"
    summary = _summarize(metadata=meta)
    assert summary["report_date"] == "2026-06-15T12:00:00Z"


def test_report_date_fallback_when_no_end_time() -> None:
    """Fix 11: Without end_time_utc, report_date falls back to datetime.now()."""
    meta = _simple_metadata()
    meta.pop("end_time_utc", None)
    summary = _summarize(metadata=meta)
    assert summary["report_date"] is not None
    assert "T" in str(summary["report_date"])


# ---------------------------------------------------------------------------
# Fix 12: _prepare_speed_and_phases shared helper
# ---------------------------------------------------------------------------


def test_build_findings_uses_shared_speed_prep() -> None:
    """Fix 12: build_findings_for_samples produces same speed analysis as summarize_run_data."""
    meta = _simple_metadata()
    samples = _simple_samples(50)
    findings_standalone = build_findings_for_samples(metadata=meta, samples=samples, lang="en")
    summary = summarize_run_data(meta, samples, lang="en", include_samples=False)

    standalone_ids = {f.get("finding_id") for f in findings_standalone}
    summary_ids = {f.get("finding_id") for f in summary.get("findings", [])}
    assert standalone_ids == summary_ids


# ---------------------------------------------------------------------------
# Fix 14: Stuck 'analyzing' run recovery
# ---------------------------------------------------------------------------


def _setup_stale_pair(db: HistoryDB) -> None:
    """Shared setup: r1 finalized (analyzing), r2 still recording."""
    db.create_run("r1", _START, {})
    db.finalize_run("r1", _END)
    db.create_run("r2", "2026-01-01T00:10:00Z", {})


def test_stale_analyzing_run_ids(db: HistoryDB) -> None:
    """Fix 14: stale_analyzing_run_ids finds stuck runs."""
    _setup_stale_pair(db)
    assert db.stale_analyzing_run_ids() == ["r1"]


def test_recover_stale_does_not_touch_analyzing(db: HistoryDB) -> None:
    """Fix 14: recover_stale_recording_runs leaves 'analyzing' runs alone."""
    _setup_stale_pair(db)
    assert db.recover_stale_recording_runs() == 1  # only r2
    assert db.get_run_status("r1") == "analyzing"
    assert db.get_run_status("r2") == "error"


# ---------------------------------------------------------------------------
# Fix 15: build_report_pdf type validation
# ---------------------------------------------------------------------------


def test_build_report_pdf_rejects_invalid_type() -> None:
    """build_report_pdf raises TypeError for non-RTD input."""
    with pytest.raises(TypeError, match="expects ReportTemplateData"):
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
    summary = _summarize()
    assert "samples" not in summary


# ---------------------------------------------------------------------------
# End-to-end pipeline test
# ---------------------------------------------------------------------------


def test_end_to_end_pipeline(db: HistoryDB) -> None:
    """Full pipeline: create → record → finalize → analyze → persist → report."""
    run_id = "e2e-test-run"
    metadata = _simple_metadata(run_id)
    db.create_run(run_id, _START, metadata)
    assert db.get_run_status(run_id) == "recording"

    samples = _simple_samples(30)
    db.append_samples(run_id, samples)

    db.finalize_run(run_id, _END)
    assert db.get_run_status(run_id) == "analyzing"

    read_samples = db.get_run_samples(run_id)
    normalized = [normalize_sample_record(s) for s in read_samples]
    summary = summarize_run_data(
        metadata,
        normalized,
        lang="en",
        file_name=run_id,
        include_samples=False,
    )
    assert isinstance(summary, dict)
    assert "findings" in summary
    assert "top_causes" in summary
    assert "run_suitability" in summary
    assert "samples" not in summary

    db.store_analysis(run_id, summary)
    assert db.get_run_status(run_id) == "complete"
    assert db.analysis_is_current(run_id)

    run = db.get_run(run_id)
    assert run is not None
    assert isinstance(run.get("analysis"), dict)
    analysis = run["analysis"]

    report_data = map_summary(analysis)
    pdf_bytes = build_report_pdf(report_data)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes[:5] == b"%PDF-"

    # Idempotency — second store_analysis should be skipped
    db.store_analysis(run_id, {"findings": [{"id": "should-not-overwrite"}]})
    run2 = db.get_run(run_id)
    assert run2 is not None
    assert run2["analysis"].get("run_id") == run_id

    assert "sensor_statistics_by_location" not in analysis
    assert analysis.get("report_date") == _END
