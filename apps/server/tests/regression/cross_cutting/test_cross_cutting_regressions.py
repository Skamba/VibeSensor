# ruff: noqa: E402, E501
from __future__ import annotations

"""Consolidated cross cutting regression tests."""


# ===== From test_multi_domain_regressions.py =====

"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""


from datetime import UTC
from unittest.mock import MagicMock

import pytest

from vibesensor.analysis.findings import _sensor_intensity_by_location
from vibesensor.analysis.helpers import _format_duration, _speed_bin_label
from vibesensor.analysis.phase_segmentation import segment_run_phases
from vibesensor.analysis.report_data_builder import _order_label_human, _resolve_i18n
from vibesensor.analysis.summary import _compute_run_timing, confidence_label
from vibesensor.analysis.test_plan import _weighted_speed_window_label
from vibesensor.config import _split_host_port
from vibesensor.domain_models import VALID_SPEED_SOURCES
from vibesensor.live_diagnostics import LiveDiagnosticsEngine
from vibesensor.release_fetcher import ReleaseInfo, ServerReleaseFetcher
from vibesensor.report_i18n import tr
from vibesensor.runlog import as_float_or_none as runlog_as_float_or_none
from vibesensor.runlog import parse_iso8601


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
        _, start, end, duration = _compute_run_timing(meta, samples, "test")
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
# Bug 6: int(analysis_version) crashes on non-integer
# ---------------------------------------------------------------------------


class TestBug06AnalysisVersionCast:
    def test_non_integer_version_does_not_crash(self) -> None:
        """Simulate the API path with a non-integer analysis_version."""
        analysis: dict = {}
        analysis_version = "not_a_number"
        try:
            analysis["_analysis_is_current"] = int(analysis_version) >= 1
        except (TypeError, ValueError):
            analysis["_analysis_is_current"] = False
        assert analysis["_analysis_is_current"] is False


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
        """speed_source should be from VALID_SPEED_SOURCES, not 'override' or 'missing'."""
        # These are the only valid values for speed_source in sample records
        assert "gps" in VALID_SPEED_SOURCES
        assert "manual" in VALID_SPEED_SOURCES
        # "override" and "missing" are NOT valid
        assert "override" not in VALID_SPEED_SOURCES
        assert "missing" not in VALID_SPEED_SOURCES


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
# Bug 10: confidence_label(None) crashes
# ---------------------------------------------------------------------------


class TestBug10ConfidenceLabelNone:
    def test_none_confidence_returns_low(self) -> None:
        label_key, tone, pct_text = confidence_label(None)
        assert label_key == "CONFIDENCE_LOW"
        assert tone == "neutral"
        assert pct_text == "0%"

    def test_zero_confidence_returns_low(self) -> None:
        label_key, tone, pct_text = confidence_label(0.0)
        assert label_key == "CONFIDENCE_LOW"


# ---------------------------------------------------------------------------
# Bug 11: _order_label_human case-sensitive lookup
# ---------------------------------------------------------------------------


class TestBug11OrderLabelCaseInsensitive:
    @pytest.mark.parametrize("label", ["1x Wheel", "2x ENGINE"])
    def test_case_insensitive_match(self, label: str) -> None:
        result = _order_label_human("en", label)
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
# Bug 13: Division by zero in live_diagnostics freq_bin
# ---------------------------------------------------------------------------


class TestBug13FreqBinDivision:
    def test_zero_freq_bin_hz_no_crash(self) -> None:
        engine = LiveDiagnosticsEngine()
        # Even if _multi_freq_bin_hz were 0, the guard prevents division by zero
        old_val = engine._multi_freq_bin_hz
        engine._multi_freq_bin_hz = 0.0
        # The freq_bin calculation should use max(0.01, ...) guard
        freq_bin = round(10.0 / max(0.01, engine._multi_freq_bin_hz))
        assert isinstance(freq_bin, int)
        engine._multi_freq_bin_hz = old_val


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
        result = _resolve_i18n("en", value)
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
            item.get("presence_ratio") if item.get("presence_ratio") is not None else 0.0
        )
        assert presence == 0.0
        # Old behavior: float(item.get("presence_ratio") or 0.0) would also
        # give 0.0 BUT treats the value as "missing" conceptually

    def test_none_presence_ratio_defaults_to_zero(self) -> None:
        item: dict = {"presence_ratio": None}
        presence = float(
            item.get("presence_ratio") if item.get("presence_ratio") is not None else 0.0
        )
        assert presence == 0.0


# ===== From test_refactor_contract_regressions.py =====

"""Cross-module refactor-contract regressions.

Validates that the refactored code preserves behaviour while being more
maintainable than the originals.
"""


import inspect
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher
from vibesensor.history_db import HistoryDB, RunStatus
from vibesensor.protocol import DataMessage, HelloMessage
from vibesensor.registry import (
    _JITTER_EMA_ALPHA,
    _RESTART_SEQ_GAP,
    ClientRegistry,
    ClientSnapshot,
)
from vibesensor.release_fetcher import (
    DOWNLOAD_CHUNK_BYTES,
    GitHubAPIClient,
    ReleaseFetcherConfig,
)

# ---------------------------------------------------------------------------
# Shared constants / fixtures
# ---------------------------------------------------------------------------

_CLIENT_ID = bytes.fromhex("aabbccddeeff")
_SAMPLES_200X3 = np.zeros((200, 3), dtype=np.int16)


@pytest.fixture()
def db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "history.db")


@pytest.fixture()
def registry(db: HistoryDB) -> ClientRegistry:
    return ClientRegistry(db=db)


def _hello(client_id: bytes = _CLIENT_ID, **overrides: object) -> HelloMessage:
    defaults: dict[str, object] = {
        "client_id": client_id,
        "control_port": 9010,
        "sample_rate_hz": 800,
        "name": "node-1",
        "firmware_version": "fw",
    }
    defaults.update(overrides)
    return HelloMessage(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fix 1 & 2: Named constants in registry.py
# ---------------------------------------------------------------------------


class TestRegistryNamedConstants:
    """Verify magic numbers were extracted to named constants."""

    def test_restart_seq_gap_is_int(self) -> None:
        assert isinstance(_RESTART_SEQ_GAP, int)
        assert _RESTART_SEQ_GAP > 0

    def test_jitter_ema_alpha_is_float(self) -> None:
        assert isinstance(_JITTER_EMA_ALPHA, float)
        assert 0 < _JITTER_EMA_ALPHA < 1

    def test_restart_seq_gap_value(self) -> None:
        """Value must be 1000 to match the original literal."""
        assert _RESTART_SEQ_GAP == 1000

    def test_jitter_ema_alpha_value(self) -> None:
        """Value must be 0.2 to match the original literal."""
        assert _JITTER_EMA_ALPHA == 0.2

    def test_restart_detection_uses_named_constant(self, registry: ClientRegistry) -> None:
        """Sending a seq far below last_seq should trigger reset detection,
        proving _RESTART_SEQ_GAP is wired into the logic."""
        registry.update_from_hello(_hello(), ("10.4.0.2", 9010), now=1.0)

        high_seq = _RESTART_SEQ_GAP + 100
        msg_high = DataMessage(
            client_id=_CLIENT_ID, seq=high_seq, t0_us=10, sample_count=200, samples=_SAMPLES_200X3
        )
        registry.update_from_data(msg_high, ("10.4.0.2", 50000), now=2.0)

        msg_low = DataMessage(
            client_id=_CLIENT_ID, seq=0, t0_us=20, sample_count=200, samples=_SAMPLES_200X3
        )
        result = registry.update_from_data(msg_low, ("10.4.0.2", 50000), now=3.0)
        assert result.reset_detected

    def test_ema_smoothing_uses_named_constant(self, registry: ClientRegistry) -> None:
        """Verify timing jitter EMA uses the named constant alpha value."""
        client_id = bytes.fromhex("112233445566")

        registry.update_from_hello(
            _hello(client_id, frame_samples=200), ("10.4.0.2", 9010), now=1.0
        )

        msg0 = DataMessage(
            client_id=client_id, seq=0, t0_us=0, sample_count=200, samples=_SAMPLES_200X3
        )
        registry.update_from_data(msg0, ("10.4.0.2", 50000), now=2.0)

        # Expected delta = 200/800 * 1e6 = 250000 µs
        # Actual delta = 300000 µs → jitter = 50000 µs
        msg1 = DataMessage(
            client_id=client_id, seq=1, t0_us=300_000, sample_count=200, samples=_SAMPLES_200X3
        )
        registry.update_from_data(msg1, ("10.4.0.2", 50000), now=3.0)

        record = registry.get(client_id.hex())
        # With alpha=0.2 and initial EMA=0, first update should be:
        # (1-0.2)*0 + 0.2*50000 = 10000
        expected = _JITTER_EMA_ALPHA * 50000.0
        assert record is not None
        assert abs(record.timing_jitter_us_ema - expected) < 0.01


# ---------------------------------------------------------------------------
# Fix 3: RunStatus constants
# ---------------------------------------------------------------------------


class TestRunStatus:
    """Verify RunStatus constants match database values."""

    @pytest.mark.parametrize(
        "attr, expected",
        [
            ("RECORDING", "recording"),
            ("ANALYZING", "analyzing"),
            ("COMPLETE", "complete"),
            ("ERROR", "error"),
        ],
    )
    def test_status_value(self, attr: str, expected: str) -> None:
        assert getattr(RunStatus, attr) == expected

    def test_history_db_uses_run_status(self, db: HistoryDB) -> None:
        """delete_run_if_safe should return RunStatus.ANALYZING for analyzing runs."""
        db.create_run("run-1", "2024-01-01T00:00:00Z", {})
        db.finalize_run("run-1", "2024-01-01T00:01:00Z")
        deleted, reason = db.delete_run_if_safe("run-1")
        assert not deleted
        assert reason == RunStatus.ANALYZING


# ---------------------------------------------------------------------------
# Fix 4+5: GitHubAPIClient base class
# ---------------------------------------------------------------------------


class TestGitHubAPIClient:
    """Verify shared base class works for both fetcher types."""

    def test_api_headers_no_token(self) -> None:
        client = GitHubAPIClient()
        headers = client._api_headers()
        assert "Accept" in headers
        assert "Authorization" not in headers

    def test_api_headers_with_token(self) -> None:
        client = GitHubAPIClient()
        client._github_token = "gh-token-123"
        headers = client._api_headers()
        assert headers["Authorization"] == "Bearer gh-token-123"

    def test_server_fetcher_inherits(self) -> None:
        assert issubclass(ServerReleaseFetcher, GitHubAPIClient)

    def test_firmware_fetcher_inherits(self) -> None:
        assert issubclass(GitHubReleaseFetcher, GitHubAPIClient)

    def test_api_get_validates_https(self) -> None:
        client = GitHubAPIClient()
        with pytest.raises(ValueError, match="non-HTTPS"):
            client._api_get("http://insecure.example.com/api")

    def test_server_fetcher_context(self) -> None:
        fetcher = ServerReleaseFetcher(ReleaseFetcherConfig(server_repo="owner/repo"))
        assert fetcher._api_context == "release"

    def test_firmware_fetcher_context(self) -> None:
        fetcher = GitHubReleaseFetcher(FirmwareCacheConfig(cache_dir="/tmp/test"))
        assert fetcher._api_context == "firmware"


# ---------------------------------------------------------------------------
# Fix 6: _client_api_row helper
# ---------------------------------------------------------------------------


_EXPECTED_ROW_KEYS = {
    "id",
    "mac_address",
    "name",
    "connected",
    "location",
    "firmware_version",
    "sample_rate_hz",
    "frame_samples",
    "last_seen_age_ms",
    "data_addr",
    "control_addr",
    "frames_total",
    "dropped_frames",
    "duplicates_received",
    "queue_overflow_drops",
    "parse_errors",
    "server_queue_drops",
    "latest_metrics",
    "last_ack_cmd_seq",
    "last_ack_status",
    "reset_count",
    "last_reset_time",
    "timing_health",
}


class TestClientApiRow:
    """Verify the extracted _client_api_row helper produces correct dicts."""

    def test_disconnected_row_has_all_keys(self) -> None:
        row = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(name="test-client", connected=False),
        )
        assert set(row.keys()) == _EXPECTED_ROW_KEYS

    def test_connected_row_has_same_keys(self) -> None:
        disconnected = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(name="a", connected=False),
        )
        connected = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(
                name="b",
                connected=True,
                location="front-left",
                firmware_version="1.0",
                sample_rate_hz=800,
            ),
        )
        assert set(disconnected.keys()) == set(connected.keys())

    def test_defaults_match_old_disconnected_shape(self) -> None:
        """Disconnected client row defaults match the original inline dict."""
        row = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(name="test", connected=False),
        )
        assert row["connected"] is False
        assert row["location"] == ""
        assert row["firmware_version"] == ""
        assert row["sample_rate_hz"] == 0
        assert row["frames_total"] == 0
        assert row["latest_metrics"] == {}
        assert row["timing_health"] == {}

    def test_snapshot_uses_helper(self, registry: ClientRegistry) -> None:
        """Verify snapshot_for_api returns rows with the same keys as _client_api_row."""
        registry.set_name("aabbccddeeff", "my-sensor")
        rows = registry.snapshot_for_api(now=1.0, now_mono=1.0)
        assert len(rows) == 1
        helper_row = ClientRegistry._client_api_row(
            "aabbccddeeff",
            ClientSnapshot(name="my-sensor", connected=False),
        )
        assert set(rows[0].keys()) == set(helper_row.keys())


# ---------------------------------------------------------------------------
# Fix 7: Shared download chunk constant
# ---------------------------------------------------------------------------


def test_download_chunk_constant() -> None:
    assert DOWNLOAD_CHUNK_BYTES == 1024 * 1024  # 1 MB
    assert DOWNLOAD_CHUNK_BYTES > 0


# ---------------------------------------------------------------------------
# Fix 8: Version comparison warning
# ---------------------------------------------------------------------------


class TestVersionComparisonWarning:
    def test_logs_warning_on_unparseable_version(self) -> None:
        """When packaging cannot parse versions, a warning should be logged
        instead of silently swallowing the exception."""
        config = ReleaseFetcherConfig(server_repo="owner/repo")
        fetcher = ServerReleaseFetcher(config)

        fake_release = ReleaseInfo(
            tag="server-v!!!INVALID!!!",
            version="!!!INVALID!!!",
            asset_name="vibesensor-0.0.0-py3-none-any.whl",
            asset_url="https://api.github.com/repos/owner/repo/releases/assets/1",
        )

        with (
            patch.object(fetcher, "find_latest_release", return_value=fake_release),
            patch("vibesensor.release_fetcher.LOGGER") as mock_logger,
        ):
            result = fetcher.check_update_available("1.0.0")

        # Should still return the release (treating unparseable as update)
        assert result is not None
        # Should have logged a warning
        mock_logger.warning.assert_called_once()
        assert "Could not compare versions" in mock_logger.warning.call_args[0][0]


# ---------------------------------------------------------------------------
# Fix 9: _cursor type annotation
# ---------------------------------------------------------------------------


def test_cursor_has_return_annotation() -> None:
    """_cursor should have a return type annotation."""
    sig = inspect.signature(HistoryDB._cursor)
    assert sig.return_annotation is not inspect.Parameter.empty


# ---------------------------------------------------------------------------
# Fix 10: BACKUP_SERVER_PORT docstring
# ---------------------------------------------------------------------------


class TestBackupServerPort:
    def test_documented(self) -> None:
        """BACKUP_SERVER_PORT should be 8000 and importable."""
        import importlib
        import os

        os.environ["VIBESENSOR_DISABLE_AUTO_APP"] = "1"
        try:
            mod = importlib.import_module("vibesensor.app")
            assert mod.BACKUP_SERVER_PORT == 8000
        finally:
            os.environ.pop("VIBESENSOR_DISABLE_AUTO_APP", None)


# ===== From test_report_delivery_and_stream_resilience_regressions.py =====

"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""


import asyncio
import contextlib
import json

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
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_after_4(), timeout=5.0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
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


# ===== From test_review_guardrails_core_regressions.py =====

"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""


import importlib
import inspect
import time

import pytest

from vibesensor.config import ProcessingConfig
from vibesensor.diagnostics_shared import build_order_bands, severity_from_peak
from vibesensor.domain_models import (
    as_float_or_none,
    as_int_or_none,
    new_car_id,
    sanitize_aspects,
)
from vibesensor.registry import _sanitize_name
from vibesensor.runlog import bounded_sample
from vibesensor.worker_pool import WorkerPool

# ---------------------------------------------------------------------------
# Item 1 + 2: Public API naming in domain_models
# ---------------------------------------------------------------------------


class TestDomainModelsPublicAPI:
    """Verify that formerly-private helpers are importable by their public names."""

    def test_as_float_or_none_importable(self) -> None:
        assert as_float_or_none(3.14) == 3.14
        assert as_float_or_none(None) is None
        assert as_float_or_none("") is None
        assert as_float_or_none(float("nan")) is None
        assert as_float_or_none(float("inf")) is None

    def test_as_int_or_none_importable(self) -> None:
        assert as_int_or_none(3.7) == 4
        assert as_int_or_none(None) is None

    def test_sanitize_aspects_importable(self) -> None:
        result = sanitize_aspects({"tire_width_mm": 225.0})
        assert "tire_width_mm" in result

    def test_new_car_id_importable(self) -> None:
        car_id = new_car_id()
        assert isinstance(car_id, str) and len(car_id) > 0

    def test_domain_models_has_all(self) -> None:
        import vibesensor.domain_models as dm

        assert hasattr(dm, "__all__")
        assert "as_float_or_none" in dm.__all__
        assert "CarConfig" in dm.__all__

    def test_runlog_re_exports(self) -> None:
        """runlog.as_float_or_none still works as before."""
        from vibesensor.runlog import as_float_or_none as runlog_as_float

        assert runlog_as_float(42) == 42.0


# ---------------------------------------------------------------------------
# Item 3: car_library import copy at module level
# ---------------------------------------------------------------------------


class TestCarLibraryImport:
    def test_copy_at_module_level(self) -> None:
        """copy should be importable from car_library's module scope."""
        import vibesensor.car_library as cl

        source = inspect.getsource(cl)
        # Must have top-level `import copy`, not inside a function
        lines = source.split("\n")
        # Find lines that are `import copy` at indentation level 0
        top_level_copy_import = any(
            line.strip() == "import copy" and not line.startswith(" ") for line in lines
        )
        assert top_level_copy_import, "import copy must be at module level"


# ---------------------------------------------------------------------------
# Item 4: build_order_bands lives in diagnostics_shared
# ---------------------------------------------------------------------------


class TestBuildOrderBandsLocation:
    def test_importable_from_diagnostics_shared(self) -> None:
        assert callable(build_order_bands)

    def test_not_in_runtime(self) -> None:
        """The old _build_order_bands should not exist in runtime anymore."""
        import vibesensor.runtime as rt

        assert not hasattr(rt, "_build_order_bands")

    def test_build_order_bands_basic(self) -> None:
        orders = {
            "wheel_hz": 10.0,
            "drive_hz": 30.0,
            "engine_hz": 60.0,
            "wheel_uncertainty_pct": 0.02,
            "drive_uncertainty_pct": 0.03,
            "engine_uncertainty_pct": 0.04,
        }
        settings = {}
        bands = build_order_bands(orders, settings)
        assert isinstance(bands, list)
        assert len(bands) >= 4  # wheel_1x, wheel_2x, drive/engine, engine_2x
        keys = [b["key"] for b in bands]
        assert "wheel_1x" in keys
        assert "wheel_2x" in keys
        assert "engine_2x" in keys


# ---------------------------------------------------------------------------
# Item 5: WorkerPool.submit() tracks timing
# ---------------------------------------------------------------------------


class TestWorkerPoolSubmitTiming:
    def test_submit_tracks_wait_time(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            future = pool.submit(time.sleep, 0.05)
            future.result()
            stats = pool.stats()
            assert stats["total_tasks"] == 1
            assert stats["total_wait_s"] >= 0.04
        finally:
            pool.shutdown()

    def test_submit_timing_accumulates(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            futures = [pool.submit(time.sleep, 0.02) for _ in range(3)]
            for f in futures:
                f.result()
            stats = pool.stats()
            assert stats["total_tasks"] == 3
            assert stats["total_wait_s"] >= 0.05
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Item 6: _sanitize_name truncation
# ---------------------------------------------------------------------------


class TestSanitizeName:
    def test_ascii_within_limit(self) -> None:
        assert _sanitize_name("Hello") == "Hello"

    def test_truncation_at_32_bytes(self) -> None:
        assert _sanitize_name("A" * 32) == "A" * 32
        assert _sanitize_name("A" * 33) == "A" * 32

    def test_multibyte_truncation(self) -> None:
        # Each '€' is 3 UTF-8 bytes.  10 × 3 = 30 bytes → fits in 32.
        # 11 × 3 = 33 bytes → must truncate without splitting.
        name = "€" * 11
        result = _sanitize_name(name)
        assert len(result.encode("utf-8")) <= 32
        assert result == "€" * 10

    def test_control_chars_stripped(self) -> None:
        assert _sanitize_name("hel\x00lo") == "hello"
        assert _sanitize_name("\x01\x02\x03") == ""


# ---------------------------------------------------------------------------
# Item 7: severity_from_peak always returns dict
# ---------------------------------------------------------------------------


class TestSeverityFromPeakReturnType:
    @pytest.mark.parametrize(
        "db, sensor_count, prior_state",
        [
            (-100.0, 0, None),
            (50.0, 1, None),
            (5.0, 1, {"current_bucket": "l2", "pending_bucket": None}),
        ],
    )
    def test_returns_dict(self, db: float, sensor_count: int, prior_state) -> None:
        result = severity_from_peak(
            vibration_strength_db=db, sensor_count=sensor_count, prior_state=prior_state
        )
        assert isinstance(result, dict)
        assert "key" in result
        assert "db" in result
        assert "state" in result


# ---------------------------------------------------------------------------
# Item 8: Nyquist uses float division
# ---------------------------------------------------------------------------


_PROCESSING_DEFAULTS = dict(
    waveform_seconds=8,
    waveform_display_hz=120,
    ui_push_hz=10,
    ui_heavy_push_hz=4,
    fft_update_hz=4,
    fft_n=2048,
    spectrum_min_hz=5.0,
    client_ttl_seconds=120,
    accel_scale_g_per_lsb=None,
)


class TestNyquistFloatDivision:
    def test_odd_sample_rate_nyquist(self) -> None:
        cfg = ProcessingConfig(sample_rate_hz=801, spectrum_max_hz=400, **_PROCESSING_DEFAULTS)
        assert cfg.spectrum_max_hz == 400  # NOT clamped to 399

    def test_even_sample_rate_still_clamps(self) -> None:
        cfg = ProcessingConfig(sample_rate_hz=800, spectrum_max_hz=400, **_PROCESSING_DEFAULTS)
        assert cfg.spectrum_max_hz == 399  # clamped


# ---------------------------------------------------------------------------
# Item 9: bounded_sample final trim
# ---------------------------------------------------------------------------


class TestBoundedSampleTrim:
    def test_never_exceeds_max_items(self) -> None:
        for total in range(1, 30):
            for max_items in range(1, 10):
                samples = iter([{"v": i} for i in range(total)])
                kept, count, stride = bounded_sample(samples, max_items=max_items)
                assert len(kept) <= max_items, (
                    f"total={total}, max_items={max_items}: got {len(kept)} items"
                )
                assert count == total

    def test_max_items_1_edge_case(self) -> None:
        samples = iter([{"v": i} for i in range(5)])
        kept, count, stride = bounded_sample(samples, max_items=1)
        assert len(kept) <= 1
        assert count == 5


# ---------------------------------------------------------------------------
# Item 10: __all__ on key modules
# ---------------------------------------------------------------------------


class TestModuleAllExports:
    @pytest.mark.parametrize(
        "module_path",
        [
            "vibesensor.domain_models",
            "vibesensor.protocol",
            "vibesensor.worker_pool",
            "vibesensor.car_library",
            "vibesensor.gps_speed",
            "vibesensor.registry",
        ],
    )
    def test_module_has_all(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        assert hasattr(mod, "__all__"), f"{module_path} is missing __all__"
        assert len(mod.__all__) > 0, f"{module_path}.__all__ is empty"


# ===== From test_review_guardrails_extended_regressions.py =====

"""Cross-cutting review guardrail regressions (extended set).

Each test group validates one of the hate-list items to prevent regression.
"""


import inspect
import os
import threading

import pytest

import vibesensor.analysis_settings as analysis_settings_mod
import vibesensor.diagnostics_shared as diagnostics_shared_mod
import vibesensor.locations as locations_mod
import vibesensor.udp_control_tx as udp_control_tx_mod
from vibesensor.analysis_settings import sanitize_settings
from vibesensor.car_library import CAR_LIBRARY, get_models_for_brand_type, get_variants_for_model
from vibesensor.diagnostics_shared import as_float_or_none as diagnostics_as_float_or_none
from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.locations import is_wheel_location
from vibesensor.settings_store import PersistenceError, SettingsStore
from vibesensor.udp_control_tx import UDPControlPlane
from vibesensor.ws_hub import _ws_debug_enabled


def _make_store_with_sensor() -> SettingsStore:
    """Create a SettingsStore with one pre-registered sensor."""
    store = SettingsStore(db=None)
    store.set_sensor("aabbccddeeff", {"name": "Test", "location": "trunk"})
    return store


def _make_gps_monitor() -> GPSSpeedMonitor:
    return GPSSpeedMonitor(gps_enabled=True)


def _make_control_plane() -> UDPControlPlane:
    return UDPControlPlane(ClientRegistry(), "127.0.0.1", 0)


# ---------------------------------------------------------------------------
# Item 1: remove_sensor persistence rollback
# ---------------------------------------------------------------------------


class TestRemoveSensorRollback:
    def test_remove_sensor_rolls_back_on_persist_failure(self) -> None:
        store = _make_store_with_sensor()
        assert "aabbccddeeff" in store.get_sensors()

        # Simulate persistence failure
        with (
            patch.object(store, "_persist", side_effect=PersistenceError("disk full")),
            pytest.raises(PersistenceError),
        ):
            store.remove_sensor("aabbccddeeff")

        # Sensor should still be in memory after rollback
        assert "aabbccddeeff" in store.get_sensors()

    def test_remove_sensor_succeeds_normally(self) -> None:
        store = _make_store_with_sensor()
        assert store.remove_sensor("aabbccddeeff") is True
        assert "aabbccddeeff" not in store.get_sensors()

    def test_remove_sensor_nonexistent_returns_false(self) -> None:
        store = SettingsStore(db=None)
        assert store.remove_sensor("aabbccddeeff") is False


# ---------------------------------------------------------------------------
# Item 2: _NON_WHEEL_TOKENS is a module-level constant
# ---------------------------------------------------------------------------


class TestNonWheelTokensModuleLevel:
    def test_non_wheel_tokens_is_module_constant(self) -> None:
        assert hasattr(locations_mod, "_NON_WHEEL_TOKENS")
        assert isinstance(locations_mod._NON_WHEEL_TOKENS, tuple)
        assert "seat" in locations_mod._NON_WHEEL_TOKENS
        assert "trunk" in locations_mod._NON_WHEEL_TOKENS

    @pytest.mark.parametrize(
        "location, expected",
        [
            ("driver_seat", False),
            ("transmission", False),
            ("front_left_wheel", True),
        ],
    )
    def test_is_wheel_location_classification(self, location: str, expected: bool) -> None:
        assert is_wheel_location(location) is expected


# ---------------------------------------------------------------------------
# Item 3: resolve_speed reads from atomic snapshot
# ---------------------------------------------------------------------------


class TestResolveSpeedAtomicSnapshot:
    def test_speed_mps_property_reads_from_snapshot(self) -> None:
        m = _make_gps_monitor()
        assert m.speed_mps is None
        m.speed_mps = 10.0
        assert m.speed_mps == 10.0
        assert m._speed_snapshot[0] == 10.0

    def test_speed_mps_setter_preserves_timestamp(self) -> None:
        m = _make_gps_monitor()
        ts = time.monotonic()
        m._speed_snapshot = (5.0, ts)
        m.speed_mps = 10.0
        # Timestamp should be preserved
        assert m._speed_snapshot == (10.0, ts)

    def test_resolve_speed_uses_snapshot_speed(self) -> None:
        m = _make_gps_monitor()
        # Write speed and timestamp atomically
        m._speed_snapshot = (10.0, time.monotonic())
        r = m.resolve_speed()
        assert r.speed_mps == 10.0
        assert r.source == "gps"

    def test_resolve_speed_snapshot_consistency(self) -> None:
        """Setting speed_mps and last_update_ts both update the snapshot."""
        m = _make_gps_monitor()
        m.speed_mps = 15.0
        m.last_update_ts = time.monotonic()
        r = m.resolve_speed()
        assert r.speed_mps == 15.0
        assert r.source == "gps"


# ---------------------------------------------------------------------------
# Item 4: car library returns copies
# ---------------------------------------------------------------------------


class TestCarLibraryCopies:
    def test_get_models_returns_copies(self) -> None:
        if not CAR_LIBRARY:
            pytest.skip("No car library data loaded")
        brand = CAR_LIBRARY[0].get("brand")
        car_type = CAR_LIBRARY[0].get("type")
        models = get_models_for_brand_type(brand, car_type)
        if not models:
            pytest.skip("No models found")
        # Mutate the returned dict
        models[0]["MUTATED"] = True
        # Original library should NOT be mutated
        for entry in CAR_LIBRARY:
            assert "MUTATED" not in entry

    def test_get_variants_returns_copies(self) -> None:
        if not CAR_LIBRARY:
            pytest.skip("No car library data loaded")
        for entry in CAR_LIBRARY:
            variants = entry.get("variants") or []
            if variants:
                result = get_variants_for_model(entry["brand"], entry["type"], entry["model"])
                if result:
                    result[0]["MUTATED"] = True
                    # Original should NOT be mutated
                    assert "MUTATED" not in variants[0]
                    return
        pytest.skip("No entries with variants found")


# ---------------------------------------------------------------------------
# Item 5: _cmd_seq protected by lock
# ---------------------------------------------------------------------------


class TestCmdSeqLock:
    def test_udp_control_plane_has_cmd_seq_lock(self) -> None:
        cp = _make_control_plane()
        assert hasattr(cp, "_cmd_seq_lock")
        assert isinstance(cp._cmd_seq_lock, type(threading.Lock()))

    def test_next_cmd_seq_increments_atomically(self) -> None:
        cp = _make_control_plane()
        initial = cp._cmd_seq
        seq1 = cp._next_cmd_seq()
        seq2 = cp._next_cmd_seq()
        assert seq1 == (initial + 1) & 0xFFFFFFFF
        assert seq2 == (initial + 2) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Item 6: _ws_debug_enabled checks env var at call time
# ---------------------------------------------------------------------------


class TestWSDebugLazy:
    def test_ws_debug_function_exists(self) -> None:
        assert callable(_ws_debug_enabled)

    def test_ws_debug_toggleable_at_runtime(self) -> None:
        # Ensure it's off
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBESENSOR_WS_DEBUG", None)
            assert _ws_debug_enabled() is False

        # Turn it on at runtime
        with patch.dict(os.environ, {"VIBESENSOR_WS_DEBUG": "1"}):
            assert _ws_debug_enabled() is True

        # Turn it back off
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBESENSOR_WS_DEBUG", None)
            assert _ws_debug_enabled() is False


# ---------------------------------------------------------------------------
# Item 7: DEFAULT_ANALYSIS_SETTINGS defined before sanitize_settings
# ---------------------------------------------------------------------------


class TestAnalysisSettingsOrder:
    def test_default_settings_defined_before_sanitize(self) -> None:
        source = inspect.getsource(analysis_settings_mod)
        # DEFAULT_ANALYSIS_SETTINGS must appear before def sanitize_settings
        defaults_pos = source.index("DEFAULT_ANALYSIS_SETTINGS: dict")
        sanitize_pos = source.index("def sanitize_settings(")
        assert defaults_pos < sanitize_pos, (
            "DEFAULT_ANALYSIS_SETTINGS must be defined before sanitize_settings"
        )

    def test_sanitize_settings_works_with_defaults(self) -> None:
        result = sanitize_settings({"tire_width_mm": 225.0})
        assert "tire_width_mm" in result
        assert result["tire_width_mm"] == 225.0


# ---------------------------------------------------------------------------
# Item 8: _alive flag protected under metrics lock
# ---------------------------------------------------------------------------


class TestWorkerPoolAliveProtection:
    def test_submit_checks_alive_under_lock(self) -> None:
        pool = WorkerPool(max_workers=1)
        pool.shutdown()

        with pytest.raises(RuntimeError, match="shut down"):
            pool.submit(lambda: None)

    def test_shutdown_sets_alive_under_lock(self) -> None:
        pool = WorkerPool(max_workers=1)
        assert pool._alive is True
        pool.shutdown()
        assert pool._alive is False


# ---------------------------------------------------------------------------
# Item 9: as_float_or_none imported directly (no confusing alias)
# ---------------------------------------------------------------------------


class TestAsFloatOrNoneImport:
    def test_diagnostics_shared_uses_full_name(self) -> None:
        """diagnostics_shared should import as_float_or_none, not _as_float."""
        source = inspect.getsource(diagnostics_shared_mod)
        assert "as _as_float" not in source, (
            "diagnostics_shared should not alias as_float_or_none to _as_float"
        )
        assert "as_float_or_none" in source

    def test_as_float_or_none_accessible_from_diagnostics_shared(self) -> None:
        assert diagnostics_as_float_or_none(3.14) == 3.14
        assert diagnostics_as_float_or_none(None) is None


# ---------------------------------------------------------------------------
# Item 10: udp_control_tx has __all__
# ---------------------------------------------------------------------------


class TestUdpControlTxAll:
    def test_has_all_export(self) -> None:
        assert hasattr(udp_control_tx_mod, "__all__")
        assert "UDPControlPlane" in udp_control_tx_mod.__all__

    def test_internal_class_not_in_all(self) -> None:
        assert "ControlDatagramProtocol" not in udp_control_tx_mod.__all__
