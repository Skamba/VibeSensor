from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.shared.types.analysis_time_range import AnalysisTimeRange
from vibesensor.use_cases.run.sample_builder import build_sample_records
from vibesensor.use_cases.run.sample_speed_context import SpeedContext


def test_sample_records_resolve_speed_context_per_sensor_analysis_window() -> None:
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


def test_sample_records_mark_unaligned_vehicle_context_missing_for_analysis_window() -> None:
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
