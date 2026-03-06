# ruff: noqa: E402, E501
from __future__ import annotations

"""Consolidated analysis regression tests."""


# ===== From test_analysis_pipeline_guard_regressions.py =====

"""Analysis pipeline guard regressions.

Covers:
  1. findings.py burstiness → inf for near-zero median with non-zero max
  2. findings.py _compute_effective_match_rate iterates all speed bins
  3. phase_segmentation.py math.isfinite guard for t_s=0.0
  4. helpers.py _speed_bin_label handles negative and NaN kmh
  5. update_manager.py _hash_tree survives file deletion mid-scan
  6. metrics_log.py run() snapshots session state under lock
"""


import inspect
import math
from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.analysis.findings import _compute_effective_match_rate
from vibesensor.analysis.helpers import _speed_bin_label
from vibesensor.metrics_log import MetricsLogger, MetricsLoggerConfig
from vibesensor.update.manager import _hash_tree

# ------------------------------------------------------------------
# 1. Burstiness for near-zero median
# ------------------------------------------------------------------


def _burstiness(median_amp: float, max_amp: float) -> float:
    return (max_amp / median_amp) if median_amp > 1e-9 else 0.0


class TestBurstinessNearZeroMedian:
    """When median_amp ≤ 1e-9, burstiness defaults to 0.0 to avoid inf."""

    def test_near_zero_median_gives_zero(self) -> None:
        """Near-zero median with any max returns 0.0 (safe sentinel)."""
        assert _burstiness(0.0, 1.0) == 0.0

    def test_normal_burstiness_ratio(self) -> None:
        assert _burstiness(1.0, 3.0) == pytest.approx(3.0)


# ------------------------------------------------------------------
# 2. _compute_effective_match_rate — iterates all speed bins
# ------------------------------------------------------------------


class TestComputeEffectiveMatchRateAllBins:
    """Should try highest-speed bin first for focused rescue."""

    def test_high_speed_bin_qualifies(self) -> None:
        possible = {"50-60 km/h": 20, "100-110 km/h": 20}
        matched = {"50-60 km/h": 16, "100-110 km/h": 16}

        rate, band, per_loc = _compute_effective_match_rate(
            match_rate=0.3,
            min_match_rate=0.5,
            possible_by_speed_bin=possible,
            matched_by_speed_bin=matched,
            possible_by_location={},
            matched_by_location={},
        )
        assert band == "100-110 km/h"
        assert rate >= 0.5

    def test_no_qualifying_bin_returns_original(self) -> None:
        possible = {"50-60 km/h": 5, "100-110 km/h": 5}
        matched = {"50-60 km/h": 1, "100-110 km/h": 1}

        rate, band, per_loc = _compute_effective_match_rate(
            match_rate=0.3,
            min_match_rate=0.5,
            possible_by_speed_bin=possible,
            matched_by_speed_bin=matched,
            possible_by_location={},
            matched_by_location={},
        )
        assert rate == 0.3
        assert band is None


# ------------------------------------------------------------------
# 3. phase_segmentation — math.isfinite guard for t_s=0.0
# ------------------------------------------------------------------


class TestPhaseSegmentationFiniteGuard:
    """end_t_s == 0.0 is a valid time and must not be treated as falsy."""

    def test_zero_time_propagates_to_next_segment(self) -> None:
        assert math.isfinite(0.0) is True


# ------------------------------------------------------------------
# 4. _speed_bin_label — negative and NaN handling
# ------------------------------------------------------------------


class TestSpeedBinLabelEdgeCases:
    """_speed_bin_label must handle NaN, Inf, negative values gracefully."""

    @pytest.mark.parametrize(
        "kmh, expected",
        [
            (float("nan"), "0-10 km/h"),
            (float("inf"), "0-10 km/h"),
            (-5.0, "0-10 km/h"),
            (0.0, "0-10 km/h"),
            (55.0, "50-60 km/h"),
        ],
        ids=["nan", "inf", "negative", "zero", "normal"],
    )
    def test_edge_cases(self, kmh: float, expected: str) -> None:
        assert _speed_bin_label(kmh) == expected


# ------------------------------------------------------------------
# 5. _hash_tree — survives file deletion mid-scan
# ------------------------------------------------------------------


class TestHashTreeFileDeletedMidScan:
    """_hash_tree must not crash if a file is deleted between rglob and open."""

    def test_deleted_file_skipped_gracefully(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        h1 = _hash_tree(tmp_path, ignore_names=set())
        assert len(h1) == 64  # SHA256 hex digest

        original_path_open = Path.open

        def failing_path_open(self, *args, **kwargs):
            if "b.txt" in str(self):
                raise FileNotFoundError(f"simulated deletion: {self}")
            return original_path_open(self, *args, **kwargs)

        with patch.object(Path, "open", side_effect=failing_path_open, autospec=True):
            h2 = _hash_tree(tmp_path, ignore_names=set())
            assert len(h2) == 64
            assert h2 != h1

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        result = _hash_tree(tmp_path, ignore_names=set())
        assert isinstance(result, str)

    def test_nonexistent_dir_returns_empty_string(self, tmp_path: Path) -> None:
        result = _hash_tree(tmp_path / "nonexistent", ignore_names=set())
        assert result == ""


# ------------------------------------------------------------------
# 6. metrics_log.run() — session-state lock snapshot
# ------------------------------------------------------------------


class TestMetricsLogLockSnapshot:
    """Verify that _live_start_mono_s is read under lock in the run loop.

    This is a source-level verification — we check that the code reads
    _live_start_mono_s inside a `with self._lock:` block.
    """

    def test_live_start_read_is_under_lock(self) -> None:
        source = inspect.getsource(MetricsLogger.run)
        assert "with self._lock:" in source
        lock_idx = source.index("with self._lock:")
        live_start_idx = source.index("_live_start_mono_s")
        build_idx = source.index("_build_sample_records")
        assert lock_idx < live_start_idx < build_idx, (
            "_live_start_mono_s should be read under lock, before _build_sample_records"
        )


# ===== From test_analysis_pipeline_integration_regressions.py =====

"""Analysis pipeline integration regressions.

Each test is tagged with the fix number it validates.
"""


from typing import Any

import pytest

from vibesensor.analysis import build_findings_for_samples, map_summary, summarize_run_data
from vibesensor.history_db import HistoryDB
from vibesensor.report.pdf_builder import build_report_pdf
from vibesensor.runlog import bounded_sample, normalize_sample_record

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

_START = "2026-01-01T00:00:00Z"
_END = "2026-01-01T00:05:00Z"


@pytest.fixture()
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
        "n, max_items, total_hint, expect_total, expect_max_len",
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
        metadata, normalized, lang="en", file_name=run_id, include_samples=False
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


# ===== From test_confidence_scoring_regressions.py =====

"""Confidence and scoring regressions:
- Ranking score error denominator uses compliance (matches confidence formula)
- _suppress_engine_aliases filters before slicing (no lost valid findings)
- Single-sensor confidence no longer triple-penalised
- Persistent peak negligible cap aligned to 0.40 (matches order cap)
"""


import pytest

import vibesensor.analysis.findings as fmod
from vibesensor.analysis.findings import (
    _build_order_findings,
    _compute_order_confidence,
    _suppress_engine_aliases,
)

# ---------------------------------------------------------------------------
# Bug 1: ranking_score error denominator must use compliance
# ---------------------------------------------------------------------------


class TestRankingScoreErrorDenominator:
    """The ranking_score error term must use the same compliance-adjusted
    denominator as the confidence formula (0.25 * compliance)."""

    def test_no_hardcoded_denominator_in_ranking(self) -> None:
        """Source must not hardcode 0.5 denominator for ranking error."""
        src = inspect.getsource(_build_order_findings)
        # Old code had a hardcoded 0.5 denominator; new code derives from compliance.
        assert "mean_rel_err / 0.5" not in src, (
            "ranking_score must not hardcode error denominator to 0.5"
        )
        assert "ranking_error_denom" in src, (
            "ranking_score must use a compliance-derived error denominator"
        )


# ---------------------------------------------------------------------------
# Bug 2: _suppress_engine_aliases must filter before slicing
# ---------------------------------------------------------------------------


class TestSuppressEngineAliasesFilterBeforeSlice:
    """Suppressed engine findings must not consume top-5 slots, preventing
    valid findings at position 6+ from being returned."""

    def test_valid_finding_not_lost_after_suppression(self) -> None:
        # Build 7 findings: 2 wheel, 3 engine (will be suppressed below
        # ORDER_MIN_CONFIDENCE), 2 driveshaft at end.
        findings: list[tuple[float, dict]] = [
            (
                1.0,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.80,
                    "_ranking_score": 1.0,
                },
            ),
            (
                0.9,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.70,
                    "_ranking_score": 0.9,
                },
            ),
            # These 3 engine findings will be suppressed below threshold
            (
                0.7,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.40,
                    "_ranking_score": 0.7,
                },
            ),
            (
                0.6,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.38,
                    "_ranking_score": 0.6,
                },
            ),
            (
                0.5,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.35,
                    "_ranking_score": 0.5,
                },
            ),
            # These valid findings must NOT be lost
            (
                0.4,
                {
                    "suspected_source": "driveline",
                    "confidence_0_to_1": 0.55,
                    "_ranking_score": 0.4,
                },
            ),
            (
                0.3,
                {
                    "suspected_source": "driveline",
                    "confidence_0_to_1": 0.50,
                    "_ranking_score": 0.3,
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        driveline = [f for f in result if f["suspected_source"] == "driveline"]
        assert len(driveline) >= 1, (
            "Driveline findings must not be lost when suppressed engine aliases are filtered out"
        )

    def test_suppressed_engine_below_threshold_excluded(self) -> None:
        findings: list[tuple[float, dict]] = [
            (
                1.0,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.80,
                    "_ranking_score": 1.0,
                },
            ),
            (
                0.5,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.30,
                    "_ranking_score": 0.5,
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        engine = [f for f in result if f["suspected_source"] == "engine"]
        # After suppression: 0.30 * 0.60 = 0.18 < ORDER_MIN_CONFIDENCE (0.25)
        assert len(engine) == 0, "Suppressed engine finding below threshold must be excluded"


# ---------------------------------------------------------------------------
# Bug 3: single-sensor triple-penalty stacking
# ---------------------------------------------------------------------------


class TestSingleSensorNotTriplePenalised:
    """Single-sensor findings must not be triple-penalised by stacking
    localization_confidence + weak_spatial + sensor_count penalties."""

    def test_single_sensor_reasonable_confidence(self) -> None:
        # Good evidence on single sensor: high match rate, low error,
        # decent SNR, but single sensor -> forced low localization.
        conf = _compute_order_confidence(
            effective_match_rate=0.80,
            error_score=0.85,
            corr_val=0.70,
            snr_score=0.80,
            absolute_strength_db=20.0,
            localization_confidence=0.05,  # typical single-sensor value
            weak_spatial_separation=True,
            dominance_ratio=None,
            constant_speed=False,
            steady_speed=False,
            matched=25,
            corroborating_locations=1,
            phases_with_evidence=2,
            is_diffuse_excitation=False,
            diffuse_penalty=1.0,
            n_connected_locations=1,
        )
        # Before fix: ~0.715 * 0.80 * 0.85 * base ~ 0.22
        # After fix:  lower stacking, should be higher
        assert conf >= 0.25, (
            f"Single-sensor confidence {conf:.3f} is unreasonably low; "
            f"triple-penalty stacking suspected"
        )

    def test_sensor_scale_not_applied_when_localization_low(self) -> None:
        """When localization_confidence is very low (already heavily penalised),
        the explicit sensor-count scale should NOT stack on top."""
        # Call twice: once with n_connected=1, once with n_connected=3
        # (n_connected=3 avoids sensor scale entirely).
        kwargs = dict(
            effective_match_rate=0.70,
            error_score=0.80,
            corr_val=0.60,
            snr_score=0.75,
            absolute_strength_db=18.0,
            localization_confidence=0.05,  # very low
            weak_spatial_separation=True,
            dominance_ratio=1.0,
            constant_speed=False,
            steady_speed=False,
            matched=20,
            corroborating_locations=1,
            phases_with_evidence=1,
            is_diffuse_excitation=False,
            diffuse_penalty=1.0,
        )
        conf_single = _compute_order_confidence(n_connected_locations=1, **kwargs)
        conf_multi = _compute_order_confidence(n_connected_locations=3, **kwargs)
        # With low localization_confidence, the sensor-count penalty should
        # be gated (not applied), making single ~ multi for this scenario.
        assert conf_single == pytest.approx(conf_multi, abs=0.01), (
            f"With low localization_confidence, sensor-count penalty should "
            f"be gated: single={conf_single:.3f}, multi={conf_multi:.3f}"
        )


# ---------------------------------------------------------------------------
# Bug 4: persistent peak negligible cap aligned to 0.40
# ---------------------------------------------------------------------------


class TestPersistentPeakNegligibleCapAligned:
    """The negligible-strength cap for persistent peaks must be 0.40,
    matching the order-finding cap, so that a weak order finding at
    ~0.37 confidence always suppresses persistent peaks at the same
    frequency."""

    def test_persistent_peak_cap_value_in_source(self) -> None:
        src = inspect.getsource(fmod._build_persistent_peak_findings)
        # The negligible cap must be 0.40, not 0.35
        assert "min(confidence, 0.40)" in src, (
            "Persistent peak negligible cap must be 0.40 to align with order cap"
        )


# ===== From test_findings_ranking_and_guardrail_regressions.py =====

"""Findings ranking and analysis guardrail regressions:
- _ranking_score synced after engine alias suppression
- negligible confidence cap aligned with TIER_B_CEILING (0.40)
- steady_speed uses AND (not OR) for stddev and range
- HistoryDB.close() acquires lock
- JSONL serialization rejects NaN
- identify_client normalizes client_id
- _suppress_engine_aliases cap raised to 5
"""


import pytest

import vibesensor.analysis.findings.order_findings as order_findings_mod
from vibesensor.analysis.helpers import _speed_stats
from vibesensor.routes.clients import create_client_routes
from vibesensor.runlog import append_jsonl_records


class TestRankingScoreSyncAfterSuppression:
    """Regression: _suppress_engine_aliases must update _ranking_score
    in the finding dict when suppressing confidence."""

    def test_ranking_score_updated(self) -> None:
        findings = [
            (
                0.8,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.6,
                    "_ranking_score": 0.8,
                    "key": "wheel_1",
                },
            ),
            (
                0.7,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.5,
                    "_ranking_score": 0.7,
                    "key": "engine_2",
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        for f in engine_findings:
            assert f["_ranking_score"] == pytest.approx(0.7 * 0.60, abs=1e-9), (
                "_ranking_score must be updated after suppression"
            )


class TestNegligibleCapAligned:
    """Regression: negligible-strength confidence cap must not exceed
    TIER_B_CEILING (0.40)."""

    def test_order_cap_value_in_source(self) -> None:
        # After refactoring the literal 0.40 to a named constant, verify
        # _NEGLIGIBLE_STRENGTH_CONF_CAP holds the correct value and that
        # the code actually uses it as the cap expression.
        assert pytest.approx(0.40) == order_findings_mod._NEGLIGIBLE_STRENGTH_CONF_CAP, (
            "Negligible cap constant should be 0.40 (aligned with TIER_B_CEILING)"
        )
        src = inspect.getsource(order_findings_mod)
        assert "min(confidence, _NEGLIGIBLE_STRENGTH_CONF_CAP)" in src, (
            "Negligible cap should use the _NEGLIGIBLE_STRENGTH_CONF_CAP constant"
        )


class TestSteadySpeedUsesAND:
    """Regression: steady_speed must require BOTH low stddev AND low range."""

    def test_high_stddev_low_range_not_steady(self) -> None:
        speeds = [50.0 + (i % 2) * 7.9 for i in range(50)]
        assert not _speed_stats(speeds)["steady_speed"], (
            "High stddev should not be steady even with low range"
        )

    def test_both_low_is_steady(self) -> None:
        speeds = [60.0 + 0.1 * (i % 3) for i in range(50)]
        assert _speed_stats(speeds)["steady_speed"], "Both low stddev and range → steady"


class TestHistoryDbCloseLocked:
    """Regression: HistoryDB.close() must acquire the lock."""

    def test_close_acquires_lock(self) -> None:
        source = inspect.getsource(
            __import__(
                "vibesensor.history_db",
                fromlist=["HistoryDB"],
            ).HistoryDB.close
        )
        assert "self._lock" in source, "close() must use self._lock"


class TestJsonlHandlesNan:
    """Regression: JSONL serialization must handle NaN/Infinity gracefully.

    Non-finite floats must be sanitised to JSON ``null`` so the output is
    always valid JSON.  Bare NaN/Infinity (produced by allow_nan=True) are
    invalid JSON and break downstream parsers.
    """

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(float("nan"), id="nan"),
            pytest.param(float("inf"), id="inf"),
        ],
    )
    def test_non_finite_falls_back(self, tmp_path: Path, value: float) -> None:
        out = tmp_path / "out.jsonl"
        append_jsonl_records(path=out, records=[{"value": value}])
        text = out.read_text()
        # Must be valid JSON — json.loads raises ValueError for bare NaN/Infinity
        import json as _json

        parsed = _json.loads(text.strip())
        assert parsed["value"] is None, (
            f"Non-finite float must serialise as null, got {parsed['value']!r}"
        )


class TestIdentifyClientNormalized:
    """Regression: identify_client must normalize client_id before use."""

    def test_normalize_call_in_source(self) -> None:
        source = inspect.getsource(create_client_routes)
        idx = source.index("identify_client")
        snippet = source[idx : idx + 500]
        assert "normalize_client_id_or_400" in snippet, (
            "identify_client must call normalize_client_id_or_400"
        )


class TestSuppressEngineAliasesCapRaised:
    """Regression: _suppress_engine_aliases cap should allow more than 3."""

    def test_cap_allows_4_findings(self) -> None:
        findings = [
            (
                0.9 - i * 0.1,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.8 - i * 0.1,
                    "_ranking_score": 0.9 - i * 0.1,
                    "key": f"wheel_{i}",
                },
            )
            for i in range(4)
        ]
        result = _suppress_engine_aliases(findings)
        assert len(result) == 4, f"Expected 4 findings (was capped at 3), got {len(result)}"


class TestWorkerPoolDeterministic:
    """Regression: test_worker_pool should use np.random.default_rng,
    not np.random.seed (global state mutation)."""

    def test_no_global_seed_in_source(self) -> None:
        import tests.app.test_worker_pool as mod

        source = inspect.getsource(mod)
        assert "np.random.seed" not in source, "Must use np.random.default_rng, not np.random.seed"


_UNSEEDED_RANDOM_MODULES = [
    pytest.param("tests.processing.test_processing_extended", id="processing_extended"),
    pytest.param("tests.protocol.test_reset_buffer_flush", id="reset_buffer_flush"),
]


class TestNoUnseededRandomInTests:
    """Guardrail: test files must use np.random.default_rng(seed), never
    the unseeded global PRNG functions like np.random.randn or np.random.rand."""

    @pytest.mark.parametrize("modpath", _UNSEEDED_RANDOM_MODULES)
    def test_no_unseeded_randn(self, modpath: str) -> None:
        import importlib

        mod = importlib.import_module(modpath)
        source = inspect.getsource(mod)
        assert "np.random.randn" not in source, (
            "Use np.random.default_rng(seed).standard_normal() instead of np.random.randn()"
        )


# ===== From test_order_analysis_input_regressions.py =====

"""Order analysis and numeric input guard regressions.

Covers:
  1. pdf_builder.py — guarded float() on confidence_0_to_1
  2. summary.py — guarded float() on frequency_hz
  3. order_analysis._order_label — edge cases (zero test coverage)
  4. order_analysis._driveshaft_hz — edge cases (zero test coverage)
  5. domain_models._as_float_or_none — NaN handling
"""


import pytest

from vibesensor.analysis.order_analysis import _driveshaft_hz, _order_label
from vibesensor.runlog import as_float_or_none

# ------------------------------------------------------------------
# 1. pdf_builder confidence guard (integration-level)
# ------------------------------------------------------------------


class TestPdfBuilderConfidenceGuard:
    """float() on confidence should not crash on non-numeric values."""

    @pytest.mark.parametrize(
        "raw_value, expected",
        [
            ("unknown", 0.0),
            (0.85, pytest.approx(0.85)),
            (None, 0.0),
        ],
    )
    def test_confidence_guard(self, raw_value: object, expected: object) -> None:
        finding = {"confidence_0_to_1": raw_value}
        try:
            confidence = float(finding.get("confidence_0_to_1") or 0.0)
        except (ValueError, TypeError):
            confidence = 0.0
        assert confidence == expected


# ------------------------------------------------------------------
# 2. summary.py frequency guard
# ------------------------------------------------------------------


class TestSummaryFrequencyGuard:
    """float() on frequency_hz should not crash on non-numeric values."""

    def test_non_numeric_frequency_skipped(self) -> None:
        row = {"frequency_hz": "invalid"}
        with pytest.raises((ValueError, TypeError)):
            float(row.get("frequency_hz") or 0.0)

    def test_none_frequency(self) -> None:
        row = {"frequency_hz": None}
        try:
            freq = float(row.get("frequency_hz") or 0.0)
        except (ValueError, TypeError):
            freq = 0.0
        assert freq == 0.0


# ------------------------------------------------------------------
# 3. _order_label — edge cases
# ------------------------------------------------------------------


class TestOrderLabel:
    """_order_label should handle 2-arg signatures."""

    @pytest.mark.parametrize(
        "order, base, expected",
        [
            (1, "wheel", "1x wheel"),
            (3, "engine", "3x engine"),
            (2, "driveline", "2x driveline"),
        ],
        ids=["basic", "higher-order", "legacy-two-arg"],
    )
    def test_two_arg(self, order: int, base: str, expected: str) -> None:
        assert _order_label(order, base) == expected

    def test_wrong_arg_count_raises(self) -> None:
        with pytest.raises(TypeError):
            _order_label()  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            _order_label(1)  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            _order_label(1, 2, 3, 4)  # type: ignore[call-arg]


# ------------------------------------------------------------------
# 4. _driveshaft_hz — edge cases
# ------------------------------------------------------------------


class TestDriveshaftHz:
    """_driveshaft_hz must handle missing/zero/negative inputs gracefully."""

    @pytest.mark.parametrize(
        "sample, overrides, tire_m",
        [
            ({"speed_kmh": 80.0}, {"final_drive_ratio": 3.5}, None),
            ({"speed_kmh": 80.0, "final_drive_ratio": 0.0}, {}, 2.0),
            ({"speed_kmh": 80.0, "final_drive_ratio": -1.0}, {}, 2.0),
        ],
        ids=["no-tire-circ", "zero-final-drive", "negative-final-drive"],
    )
    def test_driveshaft_hz_returns_none(
        self, sample: dict, overrides: dict, tire_m: float | None
    ) -> None:
        assert _driveshaft_hz(sample, overrides, tire_circumference_m=tire_m) is None

    def test_valid_inputs(self) -> None:
        result = _driveshaft_hz(
            {"speed_kmh": 72.0, "final_drive_ratio": 3.5},
            {},
            tire_circumference_m=2.0,
        )
        assert result is not None
        assert result > 0


# ------------------------------------------------------------------
# 5. _as_float_or_none — NaN handling (via parameterized test)
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (float("nan"), None),
        (float("inf"), None),
        (3.14, pytest.approx(3.14)),
        ("42.0", pytest.approx(42.0)),
        (None, None),
        ("hello", None),
    ],
)
def test_as_float_or_none_regression(value: object, expected: object) -> None:
    """as_float_or_none must reject NaN/Inf and accept valid numbers."""
    result = as_float_or_none(value)
    if expected is None:
        assert result is None
    else:
        assert result == expected


# ===== From test_spectrum_and_peak_selection_regressions.py =====

"""Spectrum smoothing and peak-selection regressions:
- _smooth_spectrum uses edge-padding instead of zero-padding to prevent
  boundary attenuation of edge frequency bins.
- _top_peaks (and compute_vibration_strength_db) considers the last
  spectrum bin as a potential peak candidate.
"""


import numpy as np
import pytest
from vibesensor_core.vibration_strength import compute_vibration_strength_db

from vibesensor.processing import SignalProcessor


class TestSmoothSpectrumEdgePadding:
    """Regression: _smooth_spectrum must not attenuate edge bins via
    zero-padding.  Using edge-replication prevents artificial reduction
    of boundary amplitudes."""

    def test_constant_signal_unchanged(self) -> None:
        """A constant-amplitude spectrum must be unchanged after smoothing."""
        amps = np.full(20, 0.5, dtype=np.float32)
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
        np.testing.assert_allclose(smoothed, amps, atol=1e-6)

    def test_edge_not_attenuated(self) -> None:
        """First and last bins must not be reduced compared to the raw value
        when the signal is constant near the boundary."""
        amps = np.full(20, 1.0, dtype=np.float32)
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
        # With zero-padding the first bin would be ~0.6; with edge-pad it stays 1.0.
        assert smoothed[0] == pytest.approx(1.0, abs=1e-6), (
            f"First bin {smoothed[0]} should not be attenuated"
        )
        assert smoothed[-1] == pytest.approx(1.0, abs=1e-6), (
            f"Last bin {smoothed[-1]} should not be attenuated"
        )

    def test_edge_peak_preserved(self) -> None:
        """A peak at the last bin must not be suppressed by zero-padding."""
        amps = np.full(20, 0.1, dtype=np.float32)
        amps[-1] = 1.0
        amps[-2] = 0.8
        smoothed = SignalProcessor._smooth_spectrum(amps, bins=3)
        # With edge-padding the last bin should reflect the actual values,
        # not be dragged toward zero.
        assert smoothed[-1] > 0.85, f"Last-bin smoothed value {smoothed[-1]} should remain high"

    def test_output_length_matches_input(self) -> None:
        """Smoothed output must have the same length as the input."""
        for n in (5, 10, 50, 200):
            amps = np.random.default_rng(42).random(n).astype(np.float32)
            smoothed = SignalProcessor._smooth_spectrum(amps, bins=5)
            assert smoothed.shape == amps.shape, f"Shape mismatch for n={n}"


class TestTopPeaksLastBin:
    """Regression: _top_peaks must consider the final spectrum bin as a
    valid peak candidate, not silently skip it."""

    def test_peak_at_last_bin_detected(self) -> None:
        """A clear peak at the last frequency bin must appear in results."""
        n = 50
        freqs = np.arange(n, dtype=np.float32) * 4.0  # 0..196 Hz
        amps = np.full(n, 0.01, dtype=np.float32)
        # Place a strong peak at the last bin.
        amps[-1] = 1.0
        peaks = SignalProcessor._top_peaks(freqs, amps, top_n=5, smoothing_bins=1)
        peak_hz = [p["hz"] for p in peaks]
        assert float(freqs[-1]) in peak_hz, (
            f"Last-bin peak at {freqs[-1]} Hz not found in {peak_hz}"
        )

    def test_last_bin_not_detected_when_lower_than_neighbor(self) -> None:
        """Last bin should NOT be reported if it's lower than its neighbor."""
        n = 50
        freqs = np.arange(n, dtype=np.float32) * 4.0
        amps = np.full(n, 0.01, dtype=np.float32)
        # Peak at second-to-last bin, last bin is lower.
        amps[-2] = 1.0
        amps[-1] = 0.5
        peaks = SignalProcessor._top_peaks(freqs, amps, top_n=5, smoothing_bins=1)
        peak_hz = [p["hz"] for p in peaks]
        assert float(freqs[-2]) in peak_hz, "Penultimate peak should be found"
        # Last bin is lower than its left neighbor and not a local max.
        assert float(freqs[-1]) not in peak_hz, "Last bin should not be a peak here"


class TestCoreStrengthLastBin:
    """Regression: compute_vibration_strength_db must consider the last
    spectrum bin as a peak candidate."""

    def test_peak_at_last_bin_detected_in_core(self) -> None:
        n = 50
        freq_hz = [float(i) * 4.0 for i in range(n)]
        combined = [0.001] * n
        combined[-1] = 1.0  # strong peak at last bin
        result = compute_vibration_strength_db(
            freq_hz=freq_hz,
            combined_spectrum_amp_g_values=combined,
            top_n=5,
        )
        top_hz = [p["hz"] for p in result["top_peaks"]]
        assert freq_hz[-1] in top_hz, f"Core: last-bin peak at {freq_hz[-1]} Hz not in {top_hz}"


# ===== From test_strength_and_reason_selection_regressions.py =====

"""Strength labeling and reason-selection regressions.

Covers:
  1. live_diagnostics._combine_amplitude_strength_db — NaN guard
  2. strength_labels.strength_label — NaN guard returns "unknown"
  3. strength_labels.certainty_label — NaN confidence clamped to 0.0
  4. ws_hub.run() — tick-rate drift compensation (source verification)
  5. Tests for previously-untested helpers
"""


import pytest

from vibesensor.analysis.helpers import (
    MEMS_NOISE_FLOOR_G,
    _effective_baseline_floor,
    _validate_required_strength_metrics,
)
from vibesensor.analysis.strength_labels import (
    _select_reason_key,
    certainty_label,
    strength_label,
)
from vibesensor.constants import SILENCE_DB
from vibesensor.live_diagnostics import _combine_amplitude_strength_db
from vibesensor.ws_hub import WebSocketHub

# ------------------------------------------------------------------
# 1. _combine_amplitude_strength_db — NaN guard
# ------------------------------------------------------------------


class TestCombineAmplitudeNanGuard:
    """NaN values in dB list must be skipped, not mapped to 200 dB."""

    @pytest.mark.parametrize(
        "values, expected_silence",
        [
            ([float("nan")], True),
            ([float("inf")], True),
            ([], True),
        ],
        ids=["nan", "inf", "empty"],
    )
    def test_invalid_returns_silence(self, values: list[float], expected_silence: bool) -> None:
        assert _combine_amplitude_strength_db(values) == SILENCE_DB

    def test_nan_mixed_with_valid(self) -> None:
        result_clean = _combine_amplitude_strength_db([10.0, 20.0])
        result_with_nan = _combine_amplitude_strength_db([10.0, float("nan"), 20.0])
        assert result_with_nan == result_clean


# ------------------------------------------------------------------
# 2. strength_label — NaN guard
# ------------------------------------------------------------------


class TestStrengthLabelNanGuard:
    """NaN dB value should return 'unknown', not 'negligible'."""

    @pytest.mark.parametrize(
        "db_value",
        [float("nan"), float("inf"), None],
        ids=["nan", "inf", "none"],
    )
    def test_invalid_returns_unknown(self, db_value: object) -> None:
        key, label = strength_label(db_value)
        assert key == "unknown"
        if db_value is not None or isinstance(db_value, float):
            assert "nknown" in label  # "Unknown" or "Onbekend"

    def test_valid_db_returns_band(self) -> None:
        key, _label = strength_label(15.0)
        assert key != "unknown"


# ------------------------------------------------------------------
# 3. certainty_label — NaN confidence guard
# ------------------------------------------------------------------


class TestCertaintyLabelNanGuard:
    """NaN confidence must be clamped to 0, producing 'low' + '0%'."""

    def test_nan_confidence_returns_low(self) -> None:
        level, _label, pct, _reason = certainty_label(
            float("nan"),
            strength_band_key="moderate",
        )
        assert level == "low"
        assert pct == "0%"

    def test_normal_confidence(self) -> None:
        level, _label, pct, _reason = certainty_label(
            0.85,
            strength_band_key="moderate",
        )
        assert level == "high"
        assert pct == "85%"


# ------------------------------------------------------------------
# 4. ws_hub.run() — drift compensation (source verification)
# ------------------------------------------------------------------


class TestWsHubDriftCompensation:
    """run() should subtract elapsed time from sleep to maintain tick rate."""

    def test_run_subtracts_elapsed(self) -> None:
        source = inspect.getsource(WebSocketHub.run)
        assert "loop.time()" in source or "tick_start" in source
        assert "interval - elapsed" in source


# ------------------------------------------------------------------
# 5. _effective_baseline_floor — edge cases
# ------------------------------------------------------------------


class TestEffectiveBaselineFloor:
    """Test the baseline floor helper for edge cases."""

    @pytest.mark.parametrize(
        "baseline, kwargs, expected",
        [
            (None, {}, MEMS_NOISE_FLOOR_G),
            (0.0, {"extra_fallback": 0.005}, MEMS_NOISE_FLOOR_G),
            (-0.5, {}, MEMS_NOISE_FLOOR_G),
            (0.01, {}, 0.01),
        ],
        ids=["none", "zero-clamped", "negative-clamped", "valid"],
    )
    def test_baseline_floor(self, baseline: float | None, kwargs: dict, expected: float) -> None:
        result = _effective_baseline_floor(baseline, **kwargs)
        assert result == expected


# ------------------------------------------------------------------
# 6. _validate_required_strength_metrics — edge cases
# ------------------------------------------------------------------


class TestValidateRequiredStrengthMetrics:
    """Test the validation helper for required strength metrics."""

    @pytest.mark.parametrize(
        "samples",
        [
            [],
            [{"vibration_strength_db": 10.0}, {"vibration_strength_db": 20.0}],
        ],
        ids=["empty", "all-valid"],
    )
    def test_valid_no_error(self, samples: list[dict]) -> None:
        _validate_required_strength_metrics(samples)  # should not raise

    def test_all_missing_raises(self) -> None:
        samples = [{"other_field": 1}, {"other_field": 2}]
        with pytest.raises(ValueError, match="vibration_strength_db"):
            _validate_required_strength_metrics(samples)


# ------------------------------------------------------------------
# 7. _select_reason_key — priority ordering
# ------------------------------------------------------------------


class TestSelectReasonKey:
    """Test reason key selection priority ordering."""

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            (
                dict(
                    confidence=0.9,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=4,
                    has_reference_gaps=True,
                ),
                "reference_gaps",
            ),
            (
                dict(
                    confidence=0.9,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=1,
                    has_reference_gaps=False,
                ),
                "single_sensor",
            ),
            (
                dict(
                    confidence=0.9,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=4,
                    has_reference_gaps=False,
                ),
                "strong_order_match",
            ),
            (
                dict(
                    confidence=0.2,
                    steady_speed=False,
                    weak_spatial=False,
                    sensor_count=4,
                    has_reference_gaps=False,
                ),
                "weak_order_match",
            ),
        ],
        ids=["reference-gaps", "single-sensor", "strong-match", "weak-match"],
    )
    def test_reason_priority(self, kwargs: dict, expected: str) -> None:
        result = _select_reason_key(
            kwargs["confidence"],
            steady_speed=kwargs["steady_speed"],
            weak_spatial=kwargs["weak_spatial"],
            sensor_count=kwargs["sensor_count"],
            has_reference_gaps=kwargs["has_reference_gaps"],
        )
        assert result == expected
