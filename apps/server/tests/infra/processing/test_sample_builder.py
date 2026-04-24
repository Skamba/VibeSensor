"""Unit tests for vibesensor.use_cases.run.sample_builder.

These tests exercise the pure functions extracted from RunRecorder,
validating that they work independently of any session lifecycle or
threading machinery.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, StrengthMetrics
from vibesensor.shared.boundaries.codecs import (
    strength_metrics_from_mapping,
    strength_peak_payloads,
)
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_to_json_object
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.shared.types.payload_types import ClientMetrics
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.run.run_metadata_builder import (
    build_run_metadata,
    firmware_version_for_run,
)
from vibesensor.use_cases.run.sample_builder import build_sample_records
from vibesensor.use_cases.run.sample_speed_context import SpeedContext
from vibesensor.use_cases.run.sample_strength_metrics import (
    dominant_hz_from_strength,
    extract_strength_data,
)

# ---------------------------------------------------------------------------
# extract_strength_data
# ---------------------------------------------------------------------------


class TestExtractStrengthData:
    def test_empty_metrics_returns_empty_strength_metrics(self) -> None:
        assert extract_strength_data(ClientMetrics()) == StrengthMetrics()

    def test_combined_strength_metrics_round_trip(self) -> None:
        metrics: ClientMetrics = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 18.5,
                    "strength_bucket": "l3",
                    "peak_amp_g": 0.02,
                    "noise_floor_amp_g": 0.001,
                    "top_peaks": [
                        {
                            "hz": 45.0,
                            "amp": 0.015,
                            "vibration_strength_db": 18.5,
                            "strength_bucket": "l3",
                        }
                    ],
                },
            },
        }
        result = extract_strength_data(metrics)
        assert result.vibration_strength_db == pytest.approx(18.5)
        assert result.strength_bucket == "l3"
        payloads = strength_peak_payloads(result.top_peaks, max_items=8)
        assert len(payloads) == 1
        assert payloads[0]["hz"] == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# dominant_hz_from_strength
# ---------------------------------------------------------------------------


class TestDominantHzFromStrength:
    def test_returns_first_peak_hz(self) -> None:
        sm = strength_metrics_from_mapping({"top_peaks": [{"hz": 42.0, "amp": 0.5}]})
        assert dominant_hz_from_strength(sm) == 42.0

    def test_empty(self) -> None:
        assert dominant_hz_from_strength(StrengthMetrics()) is None

    def test_invalid_first_peak_does_not_scan_ahead(self) -> None:
        sm = strength_metrics_from_mapping(
            {
                "top_peaks": [
                    {"hz": "bad", "amp": 0.5},
                    {"hz": 99.0, "amp": 0.4},
                ],
            },
        )
        assert dominant_hz_from_strength(sm) is None


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
        assert meta.run_id == "test-run"
        assert meta.sensor_model == "ADXL345"
        assert meta.analysis_settings.tire_width_mm == 205.0
        assert meta.analysis_settings.tire_aspect_pct == 55.0
        assert meta.analysis_settings.rim_in == 16.0

    def test_with_language(self) -> None:
        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                run_id="run-lang",
                language_reader=SimpleNamespace(language="fi"),
            ),
        )
        assert meta.language == "fi"

    def test_language_reader_defaults_to_en_when_blank(self) -> None:
        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                run_id="run-lang-default",
                language_reader=SimpleNamespace(language="   "),
            ),
        )
        assert meta.language == "en"

    def test_uses_order_reference_spec_for_tire_circumference(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _FakeSpec:
            is_complete = True
            has_engine_reference = True
            supports_wheel_reference = True
            tire_circumference_m = 2.345

        monkeypatch.setattr(
            "vibesensor.shared.types.run_schema.order_reference_spec_from_snapshot",
            lambda snapshot: _FakeSpec(),
        )

        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            ),
        )

        assert meta.incomplete_for_order_analysis is False
        assert meta.tire_circumference_m == pytest.approx(2.345)

    def test_uses_default_simulator_car_when_active_car_missing(self) -> None:
        meta = build_run_metadata(
            **_default_run_metadata_kwargs(
                firmware_version="sim-0.2",
                active_car_snapshot=None,
            ),
        )

        assert meta.car is not None
        assert meta.car.car_id == "simulator-default"
        assert meta.car.name == "VibeSensor Simulator"
        assert meta.car.car_type == "sedan"
        assert meta.car.variant is None


# ---------------------------------------------------------------------------
# build_sample_records
# ---------------------------------------------------------------------------


class TestBuildSampleRecords:
    def test_no_active_clients(self) -> None:
        reg = MagicMock()
        proc = MagicMock()
        proc.clients_with_recent_data.return_value = []
        records = build_sample_records(
            run_id="r1",
            t_s=0.0,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            speed_context=SpeedContext(None, None, "none", None, "missing"),
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
        proc.latest_analysis_time_range.return_value = AnalysisTimeRange(
            start_s=100.5,
            end_s=101.0,
            synced=True,
        )

        records = build_sample_records(
            run_id="r1",
            t_s=1.25,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            speed_context=SpeedContext(None, None, "none", None, "missing"),
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
            run_start_mono_s=100.0,
        )

        assert len(records) == 1
        frame = records[0]
        assert isinstance(frame, SensorFrame)
        assert frame.dominant_freq_hz == 15.0
        assert frame.vibration_strength_db == 22.0
        assert frame.strength_peak_amp_g == 0.15
        assert frame.strength_floor_amp_g == 0.003
        assert frame.strength_bucket == "l2"
        assert frame.analysis_window_start_us == 500_000
        assert frame.analysis_window_end_us == 1_000_000
        assert frame.analysis_window_synced is True
        assert sensor_frame_to_json_object(frame)["top_peaks"] == [
            {
                "hz": 15.0,
                "amp": 0.12,
                "vibration_strength_db": 22.0,
                "strength_bucket": "l2",
            },
        ]

    def test_uses_canonical_sensor_metadata_when_runtime_fields_are_stale(self) -> None:
        record = MagicMock()
        record.client_id = "001122334455"
        record.name = "advertised-name"
        record.location_code = ""
        record.sample_rate_hz = 400
        record.frames_dropped = 0
        record.queue_overflow_drops = 0

        reg = MagicMock()
        reg.active_client_ids.return_value = ["001122334455"]
        reg.get.return_value = record

        proc = MagicMock()
        proc.clients_with_recent_data.return_value = ["001122334455"]
        proc.latest_metrics.return_value = {"combined": {}}
        proc.latest_sample_xyz.return_value = None
        proc.latest_sample_rate_hz.return_value = 400
        proc.latest_analysis_time_range.return_value = None

        class _Reader:
            def get_sensors(self) -> dict[str, dict[str, str]]:
                return {
                    "001122334455": {
                        "name": "Rear Left Wheel",
                        "location_code": "rear_left_wheel",
                    }
                }

        records = build_sample_records(
            run_id="r1",
            t_s=1.25,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            speed_context=SpeedContext(None, None, "none", None, "missing"),
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
            sensor_metadata_reader=_Reader(),
        )

        assert len(records) == 1
        assert records[0].client_name == "Rear Left Wheel"
        assert records[0].location == "rear_left_wheel"

    def test_resolves_speed_context_per_sensor_analysis_window(self) -> None:
        first = MagicMock()
        first.client_id = "client-a"
        first.name = "Front Left"
        first.location_code = "fl"
        first.sample_rate_hz = 400
        first.frames_dropped = 0
        first.queue_overflow_drops = 0

        second = MagicMock()
        second.client_id = "client-b"
        second.name = "Rear Right"
        second.location_code = "rr"
        second.sample_rate_hz = 400
        second.frames_dropped = 0
        second.queue_overflow_drops = 0

        reg = MagicMock()
        reg.active_client_ids.return_value = ["client-a", "client-b"]
        reg.get.side_effect = lambda client_id: {"client-a": first, "client-b": second}[client_id]

        proc = MagicMock()
        proc.clients_with_recent_data.return_value = ["client-a", "client-b"]
        proc.latest_metrics.return_value = {"combined": {"strength_metrics": {}}}
        proc.latest_sample_xyz.return_value = None
        proc.latest_sample_rate_hz.return_value = 400
        proc.latest_analysis_time_range.side_effect = [
            AnalysisTimeRange(start_s=100.0, end_s=101.0, synced=True),
            AnalysisTimeRange(start_s=102.0, end_s=103.0, synced=True),
        ]

        class _SpeedProvider:
            def __init__(self) -> None:
                self.targets: list[float | None] = []

            def resolve_speed_context_at(self, target_mono_s, *, tolerance_s=None):
                self.targets.append(target_mono_s)
                lookup = {
                    100.5: 10.0,
                    102.5: 25.0,
                }
                speed_mps = lookup[target_mono_s]
                return AlignedSpeedContextSnapshot(
                    selected_speed_source="gps",
                    resolved_speed_mps=speed_mps,
                    resolved_speed_source="gps",
                    resolved_speed_aligned=True,
                    gps_speed_mps=speed_mps,
                    gps_speed_aligned=True,
                    measured_engine_rpm=None,
                    measured_engine_rpm_source=None,
                    measured_engine_rpm_aligned=False,
                )

        speed_provider = _SpeedProvider()
        records = build_sample_records(
            run_id="r1",
            t_s=3.0,
            timestamp_utc="2026-01-01T00:00:03Z",
            registry=reg,
            processor=proc,
            speed_context=SpeedContext(60.0, 60.0, "gps", None, "missing"),
            speed_provider=speed_provider,
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
            run_start_mono_s=99.0,
        )

        assert [record.client_id for record in records] == ["client-a", "client-b"]
        assert speed_provider.targets == [100.5, 102.5]
        assert records[0].speed_kmh == pytest.approx(36.0)
        assert records[1].speed_kmh == pytest.approx(90.0)
        assert records[0].speed_kmh != records[1].speed_kmh

    def test_marks_unaligned_vehicle_context_missing_for_analysis_window(self) -> None:
        record = MagicMock()
        record.client_id = "client-a"
        record.name = "Front Left"
        record.location_code = "fl"
        record.sample_rate_hz = 400
        record.frames_dropped = 0
        record.queue_overflow_drops = 0

        reg = MagicMock()
        reg.active_client_ids.return_value = ["client-a"]
        reg.get.return_value = record

        proc = MagicMock()
        proc.clients_with_recent_data.return_value = ["client-a"]
        proc.latest_metrics.return_value = {"combined": {"strength_metrics": {}}}
        proc.latest_sample_xyz.return_value = None
        proc.latest_sample_rate_hz.return_value = 400
        proc.latest_analysis_time_range.return_value = AnalysisTimeRange(
            start_s=100.0,
            end_s=101.0,
            synced=True,
        )

        class _SpeedProvider:
            def resolve_speed_context_at(self, target_mono_s, *, tolerance_s=None):
                assert target_mono_s == pytest.approx(100.5)
                return AlignedSpeedContextSnapshot(
                    selected_speed_source="gps",
                    resolved_speed_mps=None,
                    resolved_speed_source="none",
                    resolved_speed_aligned=False,
                    gps_speed_mps=None,
                    gps_speed_aligned=False,
                    measured_engine_rpm=None,
                    measured_engine_rpm_source=None,
                    measured_engine_rpm_aligned=False,
                )

        records = build_sample_records(
            run_id="r1",
            t_s=1.5,
            timestamp_utc="2026-01-01T00:00:01Z",
            registry=reg,
            processor=proc,
            speed_context=SpeedContext(88.0, 88.0, "gps", 2200.0, "obd2"),
            speed_provider=_SpeedProvider(),
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
            run_start_mono_s=99.0,
        )

        assert len(records) == 1
        assert records[0].speed_kmh is None
        assert records[0].gps_speed_kmh is None
        assert records[0].speed_source == "gps_unaligned"
        assert records[0].engine_rpm is None
        assert records[0].engine_rpm_source == "context_unaligned"
