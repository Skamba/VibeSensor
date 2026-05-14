"""Tests for canonical SensorFrame records built from live sample data."""

from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.boundaries.sensor_frames import sensor_frame_to_json_object
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.run.sample_builder import build_sample_records
from vibesensor.use_cases.run.sample_speed_context import SpeedContext


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
        assert frame.dominant_axis == ""
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

    def test_derives_dominant_axis_from_real_axis_peak_evidence(self) -> None:
        record = MagicMock()
        record.client_id = "client-1"
        record.name = "Front Left"
        record.location_code = "fl"
        record.sample_rate_hz = 400
        record.frames_dropped = 0
        record.queue_overflow_drops = 0

        reg = MagicMock()
        reg.active_client_ids.return_value = ["client-1"]
        reg.get.return_value = record

        proc = MagicMock()
        proc.clients_with_recent_data.return_value = ["client-1"]
        proc.latest_metrics.return_value = {
            "x": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 15.0, "amp": 0.12}]},
            "y": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 15.0, "amp": 0.05}]},
            "z": {"rms": 0.0, "p2p": 0.0, "peaks": []},
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
        proc.latest_sample_xyz.return_value = (0.1, 0.2, 0.3)
        proc.latest_sample_rate_hz.return_value = 400
        proc.latest_analysis_time_range.return_value = None

        records = build_sample_records(
            run_id="r1",
            t_s=1.25,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            speed_context=SpeedContext(None, None, "none", None, "missing"),
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
        )

        assert len(records) == 1
        assert records[0].dominant_axis == "x"

    def test_marks_dominant_axis_combined_when_axis_evidence_is_ambiguous(self) -> None:
        record = MagicMock()
        record.client_id = "client-1"
        record.name = "Front Left"
        record.location_code = "fl"
        record.sample_rate_hz = 400
        record.frames_dropped = 0
        record.queue_overflow_drops = 0

        reg = MagicMock()
        reg.active_client_ids.return_value = ["client-1"]
        reg.get.return_value = record

        proc = MagicMock()
        proc.clients_with_recent_data.return_value = ["client-1"]
        proc.latest_metrics.return_value = {
            "x": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 15.0, "amp": 0.12}]},
            "y": {"rms": 0.0, "p2p": 0.0, "peaks": [{"hz": 15.0, "amp": 0.12}]},
            "z": {"rms": 0.0, "p2p": 0.0, "peaks": []},
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
        proc.latest_sample_xyz.return_value = (0.1, 0.2, 0.3)
        proc.latest_sample_rate_hz.return_value = 400
        proc.latest_analysis_time_range.return_value = None

        records = build_sample_records(
            run_id="r1",
            t_s=1.25,
            timestamp_utc="2026-01-01T00:00:00Z",
            registry=reg,
            processor=proc,
            speed_context=SpeedContext(None, None, "none", None, "missing"),
            analysis_settings_snapshot=AnalysisSettingsSnapshot(),
            default_sample_rate_hz=800,
        )

        assert len(records) == 1
        assert records[0].dominant_axis == "combined"
