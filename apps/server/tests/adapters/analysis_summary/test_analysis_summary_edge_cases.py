"""Edge-case tests for analysis summary generation."""

from __future__ import annotations

from typing import Any

from vibesensor.adapters.analysis_summary import summarize_run_data


class TestSummarizeRunDataEdgeCases:
    """Integration edge cases for summarize_run_data."""

    _MINIMAL_META: dict[str, Any] = {
        "run_id": "test-edge",
        "start_time_utc": "2025-01-01T00:00:00Z",
        "end_time_utc": "2025-01-01T00:01:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
    }

    def test_empty_samples_no_crash(self) -> None:
        summary = summarize_run_data(self._MINIMAL_META, [], lang="en")
        assert summary["rows"] == 0
        assert summary.get("run_suitability") is not None

    def test_samples_with_all_none_axes(self) -> None:
        samples: list[dict[str, Any]] = [
            {
                "t_s": i,
                "client_id": "c1",
                "location": "front",
                "vibration_strength_db": 0.0,
                "strength_bucket": "l1",
            }
            for i in range(10)
        ]
        summary = summarize_run_data(self._MINIMAL_META, samples, lang="en")
        assert summary["rows"] == 10
        accel_sanity = summary.get("data_quality", {}).get("accel_sanity", {})
        assert accel_sanity.get("saturation_count") == 0

    def test_single_sample_no_crash(self) -> None:
        samples: list[dict[str, Any]] = [
            {
                "t_s": 0,
                "client_id": "c1",
                "location": "front",
                "accel_x_g": 0.1,
                "accel_y_g": 0.0,
                "accel_z_g": 1.0,
                "vibration_strength_db": 5.0,
                "strength_bucket": "l1",
            },
        ]
        summary = summarize_run_data(self._MINIMAL_META, samples, lang="en")
        assert summary["rows"] == 1
        assert summary.get("findings") is not None

    def test_nl_lang_no_crash(self) -> None:
        summary = summarize_run_data(self._MINIMAL_META, [], lang="nl")
        assert summary["lang"] == "nl"

    def test_missing_metadata_fields(self) -> None:
        summary = summarize_run_data({"run_id": "minimal"}, [], lang="en")
        assert summary["run_id"] == "minimal"
