from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.use_cases.run.sample_builder import build_sample_records
from vibesensor.use_cases.run.sample_speed_context import SpeedContext


def test_sample_records_use_canonical_sensor_metadata_when_runtime_fields_are_stale() -> None:
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
