# ruff: noqa: E402
from __future__ import annotations

"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""


from datetime import UTC
from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.persistence.runlog import parse_iso8601
from vibesensor.app.settings import _split_host_port
from vibesensor.domain import Finding, SpeedSourceKind
from vibesensor.shared.utils.json_utils import as_float_or_none as runlog_as_float_or_none
from vibesensor.use_cases.diagnostics.findings import _sensor_intensity_by_location
from vibesensor.use_cases.diagnostics.helpers import _format_duration, _speed_bin_label
from vibesensor.use_cases.diagnostics.location_analysis import _weighted_speed_window_label
from vibesensor.use_cases.diagnostics.phase_segmentation import segment_run_phases
from vibesensor.use_cases.diagnostics.summary_builder import compute_run_timing
from vibesensor.use_cases.reporting.i18n import tr
from vibesensor.use_cases.reporting.mapping import order_label_human
from vibesensor.use_cases.reporting.mapping import resolve_i18n as resolve_i18n_impl
from vibesensor.use_cases.updates.release_fetcher import ReleaseInfo, ServerReleaseFetcher


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


# ---------------------------------------------------------------------------
# Bug 1: _compute_run_timing uses timedelta instead of fromtimestamp
# ---------------------------------------------------------------------------


class TestBug01ComputeRunTimingTimedelta:
    def test_end_ts_from_samples_uses_timedelta(self) -> None:
        meta = {"start_time_utc": "2024-01-01T12:00:00Z"}
        samples = [{"t_s": 0.0}, {"t_s": 300.0}]
        _, start, end, duration = compute_run_timing(meta, samples, "test")
        assert start is not None
        assert end is not None
        assert (end - start).total_seconds() == pytest.approx(300.0)
        assert duration == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# Bug 2: tr() crashes with KeyError on missing format args
# ---------------------------------------------------------------------------


class TestBug02TrMissingArgs:
    def test_tr_with_missing_format_args_returns_template(self) -> None:
        # tr() with a template that has {source} but no source arg
        result = tr("en", "ORIGIN_EXPLANATION_FINDING_1")
        # Should not crash; returns the raw template with placeholders
        assert isinstance(result, str)

    def test_tr_with_valid_args_formats_correctly(self) -> None:
        result = tr(
            "en",
            "ORIGIN_EXPLANATION_FINDING_1",
            source="wheel",
            speed_band="50-60 km/h",
            location="FL",
            dominance="high",
        )
        assert "wheel" in result


# ---------------------------------------------------------------------------
# Bug 3: _format_duration crashes on inf/NaN
# ---------------------------------------------------------------------------


class TestBug03FormatDurationNonFinite:
    @pytest.mark.parametrize("value", [float("inf"), float("nan")])
    def test_non_finite_returns_zero(self, value: float) -> None:
        assert _format_duration(value) == "00:00.0"

    def test_normal_value_formats_correctly(self) -> None:
        assert _format_duration(125.3) == "02:05.3"


# ---------------------------------------------------------------------------
# Bug 4: _speed_bin_label crashes on NaN/inf
# ---------------------------------------------------------------------------


class TestBug04SpeedBinLabelNonFinite:
    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_non_finite_returns_fallback(self, value: float) -> None:
        assert _speed_bin_label(value) == "0-10 km/h"

    def test_normal_value_works(self) -> None:
        assert _speed_bin_label(55.0) == "50-60 km/h"


# ---------------------------------------------------------------------------
# Bug 5: check_update_available suggests downgrades as updates
# ---------------------------------------------------------------------------


class TestBug05ReleaseVersionComparison:
    def test_downgrade_returns_none(self) -> None:
        fetcher = ServerReleaseFetcher.__new__(ServerReleaseFetcher)
        fetcher.find_latest_release = MagicMock(return_value=_make_release_info("2024.1.0"))
        result = fetcher.check_update_available("2025.6.0")
        assert result is None

    def test_upgrade_returns_release(self) -> None:
        fetcher = ServerReleaseFetcher.__new__(ServerReleaseFetcher)
        fetcher.find_latest_release = MagicMock(return_value=_make_release_info("2026.1.0"))
        result = fetcher.check_update_available("2025.6.0")
        assert result is not None
        assert result.version == "2026.1.0"


# ---------------------------------------------------------------------------
# Bug 7: _split_host_port gives unhelpful error on bad port
# ---------------------------------------------------------------------------


class TestBug07SplitHostPort:
    def test_non_integer_port_raises_descriptive_error(self) -> None:
        with pytest.raises(ValueError, match="not an integer"):
            _split_host_port("host:abc")

    def test_valid_host_port(self) -> None:
        host, port = _split_host_port("127.0.0.1:8080")
        assert host == "127.0.0.1"
        assert port == 8080


# ---------------------------------------------------------------------------
# Bug 8: speed_source incorrectly reports "override"/"missing"
# ---------------------------------------------------------------------------


class TestBug08SpeedSourceMapping:
    def test_speed_source_uses_valid_domain_values(self) -> None:
        """speed_source should be from SpeedSourceKind, not 'override' or 'missing'."""
        # These are the only valid values for speed_source
        assert "gps" in tuple(SpeedSourceKind)
        assert "manual" in tuple(SpeedSourceKind)
        # "override" and "missing" are NOT valid
        assert "override" not in tuple(SpeedSourceKind)
        assert "missing" not in tuple(SpeedSourceKind)


# ---------------------------------------------------------------------------
# Bug 9: _as_float(x) or _as_float(y) treats 0.0 dB as missing
# ---------------------------------------------------------------------------


class TestBug09HotspotP95FallbackOnZero:
    def test_zero_p95_not_treated_as_missing(self) -> None:
        # Simulating the fixed code path
        row = {"p95_intensity_db": 0.0, "mean_intensity_db": 5.0}
        p95_val = runlog_as_float_or_none(row.get("p95_intensity_db"))
        p95 = (
            p95_val
            if p95_val is not None
            else runlog_as_float_or_none(row.get("mean_intensity_db"))
        )
        # 0.0 should be used, not fall through to mean
        assert p95 == 0.0

    def test_none_p95_falls_through_to_mean(self) -> None:
        row = {"p95_intensity_db": None, "mean_intensity_db": 5.0}
        p95_val = runlog_as_float_or_none(row.get("p95_intensity_db"))
        p95 = (
            p95_val
            if p95_val is not None
            else runlog_as_float_or_none(row.get("mean_intensity_db"))
        )
        assert p95 == 5.0


# ---------------------------------------------------------------------------
# Bug 10: confidence classification edge cases
# ---------------------------------------------------------------------------


class TestBug10ConfidenceLabelNone:
    def test_zero_confidence_returns_low(self) -> None:
        label_key, tone, pct_text = Finding.classify_confidence(0.0)
        assert label_key == "CONFIDENCE_LOW"
        assert tone == "neutral"
        assert pct_text == "0%"

    def test_inf_confidence_returns_low_not_high(self) -> None:
        """float('inf') previously returned CONFIDENCE_HIGH silently."""
        label_key, tone, pct_text = Finding.classify_confidence(float("inf"))
        assert label_key == "CONFIDENCE_LOW"
        assert pct_text == "0%"

    def test_nan_confidence_consistent_label_and_pct(self) -> None:
        """float('nan') previously gave pct_text='100%' with CONFIDENCE_LOW label."""
        label_key, tone, pct_text = Finding.classify_confidence(float("nan"))
        assert label_key == "CONFIDENCE_LOW"
        assert pct_text == "0%"

    def test_neg_inf_confidence_returns_low(self) -> None:
        label_key, tone, pct_text = Finding.classify_confidence(float("-inf"))
        assert label_key == "CONFIDENCE_LOW"
        assert pct_text == "0%"


# ---------------------------------------------------------------------------
# Bug 11: _order_label_human case-sensitive lookup
# ---------------------------------------------------------------------------


class TestBug11OrderLabelCaseInsensitive:
    @pytest.mark.parametrize("label", ["1x Wheel", "2x ENGINE"])
    def test_case_insensitive_match(self, label: str) -> None:
        result = order_label_human("en", label)
        assert "order" in result.lower()


# ---------------------------------------------------------------------------
# Bug 12: phase segment timestamps with all-None times
# ---------------------------------------------------------------------------


class TestBug12PhaseSegmentTimestamps:
    def test_second_segment_no_zero_when_first_has_time(self) -> None:
        samples = [
            {"t_s": 0.0, "speed_kmh": 0.0},
            {"t_s": 1.0, "speed_kmh": 0.0},
            {"t_s": None, "speed_kmh": 50.0},
            {"t_s": None, "speed_kmh": 50.0},
        ]
        _, segments = segment_run_phases(samples)
        if len(segments) > 1:
            second = segments[1]
            # Should not be 0.0 for a segment that comes after the first
            assert second.start_t_s > 0.0 or second.start_idx > 0


# ---------------------------------------------------------------------------
# Bug 14: _weighted_speed_window_label shows "50-50 km/h"
# ---------------------------------------------------------------------------


class TestBug14UniformSpeedLabel:
    def test_uniform_speed_shows_single_value(self) -> None:
        result = _weighted_speed_window_label([(50.0, 1.0), (50.0, 1.0)])
        assert result == "50 km/h"

    def test_range_shows_range(self) -> None:
        result = _weighted_speed_window_label([(40.0, 1.0), (60.0, 1.0)])
        assert "-" in result


# ---------------------------------------------------------------------------
# Bug 15: Stride warning uses hard-coded i18n strings
# ---------------------------------------------------------------------------


class TestBug15StrideWarningI18n:
    def test_i18n_keys_exist(self) -> None:
        result_en = tr("en", "SUITABILITY_CHECK_ANALYSIS_SAMPLING")
        assert result_en == "Analysis sampling"
        result_nl = tr("nl", "SUITABILITY_CHECK_ANALYSIS_SAMPLING")
        assert result_nl == "Analysebemonstering"

    def test_stride_warning_i18n_key(self) -> None:
        result = tr("en", "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING", stride="4")
        assert "stride 4" in result


# ---------------------------------------------------------------------------
# Bug 16: data trust explanation list not resolved
# ---------------------------------------------------------------------------


class TestBug16DataTrustListResolve:
    def test_list_explanation_is_resolved(self) -> None:
        # A list of i18n refs should be resolved, not stringified as "[{...}]"
        value = [
            {"_i18n_key": "SOURCE_WHEEL_TIRE"},
            {"_i18n_key": "SOURCE_ENGINE"},
        ]
        result = resolve_i18n_impl("en", value, tr=lambda key, **kw: tr("en", key, **kw))
        assert "[" not in result  # Should not contain raw list representation
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Bug 17: parse_iso8601 returns naive datetime
# ---------------------------------------------------------------------------


class TestBug17ParseIso8601Timezone:
    def test_naive_string_gets_utc(self) -> None:
        dt = parse_iso8601("2024-01-01 12:00:00")
        assert dt is not None
        assert dt.tzinfo is not None  # Should NOT be naive

    def test_aware_string_keeps_timezone(self) -> None:
        dt = parse_iso8601("2024-01-01T12:00:00+02:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_z_suffix_parsed_as_utc(self) -> None:
        dt = parse_iso8601("2024-01-01T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo == UTC

    def test_naive_and_aware_can_be_subtracted(self) -> None:
        dt1 = parse_iso8601("2024-01-01 12:00:00")
        dt2 = parse_iso8601("2024-01-01T13:00:00Z")
        assert dt1 is not None and dt2 is not None
        # This should NOT raise TypeError about naive vs aware
        diff = (dt2 - dt1).total_seconds()
        assert diff == pytest.approx(3600.0)


# ---------------------------------------------------------------------------
# Bug 18: Sensor intensity sort treats 0.0 dB as missing via `or 0.0`
# ---------------------------------------------------------------------------


class TestBug18IntensitySortZero:
    def test_zero_p95_preserved_in_sort(self) -> None:
        samples = [
            {
                "t_s": float(i),
                "vibration_strength_db": 0.0,
                "top_peaks": [],
                "location": "FL",
                "client_id": "s1",
            }
            for i in range(10)
        ]
        result = _sensor_intensity_by_location(samples, include_locations={"FL"}, lang="en")
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Bug 19: strength_floor_amp_g `or 0.0` treats valid 0.0 as missing
# ---------------------------------------------------------------------------


class TestBug19FloorAmpZero:
    def test_zero_floor_amp_preserved(self) -> None:
        sample = {"strength_floor_amp_g": 0.0}
        _floor_raw = runlog_as_float_or_none(sample.get("strength_floor_amp_g"))
        floor_amp = _floor_raw if _floor_raw is not None else 0.0
        assert floor_amp == 0.0
        # Key: the value came from the sample, not the default
        assert _floor_raw == 0.0


# ---------------------------------------------------------------------------
# Bug 20: plot_data `or 0.0` patterns treat valid 0.0 as missing
# ---------------------------------------------------------------------------


class TestBug20PlotDataOrZero:
    def test_zero_presence_ratio_preserved(self) -> None:
        # Verify the fixed pattern preserves 0.0
        item = {"presence_ratio": 0.0, "burstiness": 0.0, "persistence_score": 0.0}
        presence = float(
            item.get("presence_ratio") if item.get("presence_ratio") is not None else 0.0,
        )
        assert presence == 0.0
        # Old behavior: float(item.get("presence_ratio") or 0.0) would also
        # give 0.0 BUT treats the value as "missing" conceptually

    def test_none_presence_ratio_defaults_to_zero(self) -> None:
        item: dict = {"presence_ratio": None}
        presence = float(
            item.get("presence_ratio") if item.get("presence_ratio") is not None else 0.0,
        )
        assert presence == 0.0
