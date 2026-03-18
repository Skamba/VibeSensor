"""Unit tests for vibesensor.use_cases.run.sample_builder.

These tests exercise the pure functions extracted from RunRecorder,
validating that they work independently of any session lifecycle or
threading machinery.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, StrengthMetrics
from vibesensor.use_cases.run.sample_builder import (
    build_run_metadata,
    build_sample_records,
    dominant_hz_from_strength,
    extract_strength_data,
    firmware_version_for_run,
    resolve_speed_context,
    safe_metric,
)

# ---------------------------------------------------------------------------
# safe_metric
# ---------------------------------------------------------------------------


class TestSafeMetric:
    def test_valid_float(self) -> None:
        assert safe_metric({"x": {"rms": 0.05}}, "x", "rms") == 0.05

    def test_missing_axis(self) -> None:
        assert safe_metric({"x": {"rms": 0.05}}, "y", "rms") is None

    def test_missing_key(self) -> None:
        assert safe_metric({"x": {"rms": 0.05}}, "x", "p2p") is None

    def test_nan(self) -> None:
        assert safe_metric({"x": {"rms": float("nan")}}, "x", "rms") is None

    def test_inf(self) -> None:
        assert safe_metric({"x": {"rms": float("inf")}}, "x", "rms") is None

    def test_non_numeric(self) -> None:
        assert safe_metric({"x": {"rms": "abc"}}, "x", "rms") is None

    def test_non_dict_axis(self) -> None:
        assert safe_metric({"x": "not_dict"}, "x", "rms") is None


# ---------------------------------------------------------------------------
# extract_strength_data
# ---------------------------------------------------------------------------


class TestExtractStrengthData:
    def test_with_combined_strength_metrics(self) -> None:
        metrics = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 22.0,
                    "strength_bucket": "l2",
                    "peak_amp_g": 0.15,
                    "noise_floor_amp_g": 0.003,
                    "top_peaks": [
                        {
                            "hz": 15.0,
                            "amp": 0.12,
                            "vibration_strength_db": 22.0,
                            "strength_bucket": "l2",
                        },
                    ],
                },
            },
        }
        sm = extract_strength_data(metrics)
        assert isinstance(sm, StrengthMetrics)
        assert sm.vibration_strength_db == 22.0
        assert sm.strength_bucket == "l2"
        assert sm.peak_amp_g == 0.15
        assert sm.noise_floor_amp_g == 0.003
        assert sm.dominant_hz == 15.0
        assert sm.to_peak_payloads(max_items=8) == [
            {
                "hz": 15.0,
                "amp": 0.12,
                "vibration_strength_db": 22.0,
                "strength_bucket": "l2",
            },
        ]

    def test_empty_metrics(self) -> None:
        sm = extract_strength_data({})
        assert isinstance(sm, StrengthMetrics)
        assert sm.vibration_strength_db is None
        assert sm.peak_amp_g is None
        assert sm.noise_floor_amp_g is None
        assert sm.to_peak_payloads(max_items=8) == []

    def test_invalid_peak_skipped(self) -> None:
        metrics = {
            "combined": {
                "strength_metrics": {
                    "top_peaks": [
                        {"hz": "bad", "amp": 0.1},  # non-numeric
                        {"hz": 0, "amp": 0.1},  # zero hz
                        {"hz": 10.0, "amp": float("nan")},  # nan amp
                    ],
                },
            },
        }
        sm = extract_strength_data(metrics)
        assert sm.dominant_hz is None
        assert sm.to_peak_payloads(max_items=8) == []

    def test_max_8_peaks(self) -> None:
        metrics = {
            "combined": {
                "strength_metrics": {
                    "top_peaks": [{"hz": float(i), "amp": 0.01} for i in range(1, 12)],
                },
            },
        }
        sm = extract_strength_data(metrics)
        assert len(sm.top_peaks) == 11
        assert len(sm.to_peak_payloads(max_items=8)) == 8


# ---------------------------------------------------------------------------
# dominant_hz_from_strength
# ---------------------------------------------------------------------------


class TestDominantHzFromStrength:
    def test_returns_first_peak_hz(self) -> None:
        sm = StrengthMetrics.from_dict({"top_peaks": [{"hz": 42.0, "amp": 0.5}]})
        assert dominant_hz_from_strength(sm) == 42.0

    def test_empty(self) -> None:
        assert dominant_hz_from_strength(StrengthMetrics()) is None

    def test_invalid_first_peak_does_not_scan_ahead(self) -> None:
        sm = StrengthMetrics.from_dict(
            {
                "top_peaks": [
                    {"hz": "bad", "amp": 0.5},
                    {"hz": 99.0, "amp": 0.4},
                ],
            },
        )
        assert dominant_hz_from_strength(sm) is None


# ---------------------------------------------------------------------------
# resolve_speed_context
# ---------------------------------------------------------------------------


class TestResolveSpeedContext:
    def test_no_speed(self) -> None:
        gps = MagicMock()
        gps.speed_mps = None
        gps.effective_speed_mps = None
        gps.resolve_speed.return_value = MagicMock(source="none")
        settings = AnalysisSettingsSnapshot()
        speed, gps_speed, source, rpm = resolve_speed_context(gps, settings)
        assert speed is None
        assert rpm is None
        assert source == "none"

    def test_gps_speed(self) -> None:
        gps = MagicMock()
        gps.speed_mps = 10.0
        gps.resolve_speed.return_value = MagicMock(source="gps", speed_mps=10.0)
        settings = AnalysisSettingsSnapshot(
            tire_width_mm=205.0,
            tire_aspect_pct=55.0,
            rim_in=16.0,
            final_drive_ratio=3.73,
            current_gear_ratio=1.0,
        )
        speed, gps_speed, source, rpm = resolve_speed_context(gps, settings)
        assert speed == pytest.approx(36.0, rel=0.01)
        assert source == "gps"
        assert rpm is not None and rpm > 0

    def test_uses_order_reference_spec_for_engine_rpm(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _FakeSpec:
            def engine_rpm_from_speed_kmh(self, speed_kmh: float) -> float | None:
                return 1234.5 if speed_kmh > 0 else None

        monkeypatch.setattr(
            AnalysisSettingsSnapshot,
            "order_reference_spec",
            property(lambda self: _FakeSpec()),
        )
        gps = MagicMock()
        gps.speed_mps = 10.0
        gps.resolve_speed.return_value = MagicMock(source="gps", speed_mps=10.0)
        settings = AnalysisSettingsSnapshot()

        speed, _, _, rpm = resolve_speed_context(gps, settings)

        assert speed == pytest.approx(36.0, rel=0.01)
        assert rpm == 1234.5


# ---------------------------------------------------------------------------
# firmware_version_for_run
# ---------------------------------------------------------------------------


class TestFirmwareVersionForRun:
    def test_no_clients(self) -> None:
        reg = MagicMock()
        reg.active_client_ids.return_value = []
        assert firmware_version_for_run(reg) is None

    def test_single_version(self) -> None:
        record = MagicMock()
        record.firmware_version = "1.2.3"
        reg = MagicMock()
        reg.active_client_ids.return_value = ["c1"]
        reg.get.return_value = record
        assert firmware_version_for_run(reg) == "1.2.3"

    def test_multiple_versions_sorted(self) -> None:
        def _get(cid: str):
            m = MagicMock()
            m.firmware_version = {"c1": "1.0.0", "c2": "2.0.0"}[cid]
            return m

        reg = MagicMock()
        reg.active_client_ids.return_value = ["c1", "c2"]
        reg.get.side_effect = _get
        assert firmware_version_for_run(reg) == "1.0.0, 2.0.0"

    def test_blank_and_missing_versions_are_ignored(self) -> None:
        def _get(cid: str):
            m = MagicMock()
            m.firmware_version = {"c1": " ", "c2": None}.get(cid)
            return m

        reg = MagicMock()
        reg.active_client_ids.return_value = ["c1", "c2"]
        reg.get.side_effect = _get
        assert firmware_version_for_run(reg) is None


# ---------------------------------------------------------------------------
# build_run_metadata
# ---------------------------------------------------------------------------


def _default_run_metadata_kwargs(**overrides) -> dict:
    """Return default kwargs for ``build_run_metadata``, merging *overrides*."""
    defaults: dict = {
        "run_id": "test-run",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "analysis_settings_snapshot": AnalysisSettingsSnapshot(),
        "sensor_model": "test",
        "firmware_version": None,
        "default_sample_rate_hz": 800,
        "metrics_log_hz": 4,
        "fft_window_size_samples": 512,
        "accel_scale_g_per_lsb": None,
    }
    defaults.update(overrides)
    return defaults


class TestBuildRunMetadata:
    def test_includes_core_fields_and_tire_spec(self) -> None:
        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                sensor_model="ADXL345",
                fft_window_size_samples=1024,
                analysis_settings_snapshot=AnalysisSettingsSnapshot(
                    tire_width_mm=205.0,
                    tire_aspect_pct=55.0,
                    rim_in=16.0,
                ),
            ),
        )
        assert meta["run_id"] == "test-run"
        assert meta["sensor_model"] == "ADXL345"
        assert meta["tire_width_mm"] == 205.0
        assert meta["tire_aspect_pct"] == 55.0
        assert meta["rim_in"] == 16.0

    def test_with_language(self) -> None:
        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                run_id="run-lang",
                language_provider=lambda: "fi",
            ),
        )
        assert meta["language"] == "fi"

    def test_language_provider_defaults_to_en_when_blank(self) -> None:
        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                run_id="run-lang-default",
                language_provider=lambda: "   ",
            ),
        )
        assert meta["language"] == "en"

    def test_uses_order_reference_spec_for_tire_circumference(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _FakeSpec:
            tire_circumference_m = 2.345

        monkeypatch.setattr(
            AnalysisSettingsSnapshot,
            "order_reference_spec",
            property(lambda self: _FakeSpec()),
        )

        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            ),
        )

        assert meta["tire_circumference_m"] == 2.345


# ---------------------------------------------------------------------------
# build_sample_records
# ---------------------------------------------------------------------------


class TestBuildSampleRecords:
    def test_no_active_clients(self) -> None:
        reg = MagicMock()
        proc = MagicMock()
        gps = MagicMock()
        gps.speed_mps = None
        gps.effective_speed_mps = None
        gps.resolve_speed.return_value = MagicMock(source="none")
        proc.clients_with_recent_data.return_value = []
        records = build_sample_records(
            run_id="r1",
            t_s=0.0,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            gps_monitor=gps,
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
        )
        assert records == []

    def test_serializes_typed_strength_metrics_only_at_sensor_frame_boundary(self) -> None:
        record = MagicMock()
        record.client_id = "client-1"
        record.name = "Front Left"
        record.location_code = "fl"
        record.sample_rate_hz = 400
        record.frames_dropped = 1
        record.queue_overflow_drops = 2

        reg = MagicMock()
        reg.active_client_ids.return_value = ["client-1"]
        reg.get.return_value = record

        proc = MagicMock()
        proc.clients_with_recent_data.return_value = ["client-1"]
        proc.latest_metrics.return_value = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 22.0,
                    "peak_amp_g": 0.15,
                    "noise_floor_amp_g": 0.003,
                    "top_peaks": [
                        {
                            "hz": 15.0,
                            "amp": 0.12,
                            "vibration_strength_db": 22.0,
                            "strength_bucket": "l2",
                        },
                        {
                            "hz": 0.0,
                            "amp": 0.99,
                            "vibration_strength_db": 99.0,
                            "strength_bucket": "l5",
                        },
                    ],
                },
            },
        }
        proc.latest_sample_xyz.return_value = (0.1, 0.2, 0.3)
        proc.latest_sample_rate_hz.return_value = 400

        gps = MagicMock()
        gps.speed_mps = None
        gps.resolve_speed.return_value = MagicMock(source="none", speed_mps=None)

        records = build_sample_records(
            run_id="r1",
            t_s=1.25,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            gps_monitor=gps,
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
        )

        assert len(records) == 1
        frame = records[0]
        assert frame["dominant_freq_hz"] == 15.0
        assert frame["vibration_strength_db"] == 22.0
        assert frame["strength_peak_amp_g"] == 0.15
        assert frame["strength_floor_amp_g"] == 0.003
        assert frame["strength_bucket"] == "l2"
        assert frame["top_peaks"] == [
            {
                "hz": 15.0,
                "amp": 0.12,
                "vibration_strength_db": 22.0,
                "strength_bucket": "l2",
            },
        ]
