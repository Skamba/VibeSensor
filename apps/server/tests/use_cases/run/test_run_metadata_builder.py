"""Focused tests for run metadata assembly."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, CarOrderReferenceStatus, CarSnapshot
from vibesensor.shared.types.run_schema import RunCarMetadata
from vibesensor.use_cases.run.run_metadata_builder import (
    build_run_metadata,
    firmware_version_for_run,
)


def _default_run_metadata_kwargs(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
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


def test_build_run_metadata_carries_active_car_override_provenance() -> None:
    metadata = build_run_metadata(
        run_id="run-1",
        start_time_utc="2026-04-25T00:00:00Z",
        analysis_settings_snapshot=AnalysisSettingsSnapshot(
            tire_width_mm=245.0,
            tire_aspect_pct=40.0,
            rim_in=18.0,
            final_drive_ratio=3.91,
            current_gear_ratio=0.82,
        ),
        sensor_model="fixture-sensor",
        firmware_version="1.2.3",
        default_sample_rate_hz=800,
        metrics_log_hz=10,
        fft_window_size_samples=1024,
        accel_scale_g_per_lsb=0.001,
        active_car_snapshot=CarSnapshot(
            car_id="car-1",
            name="Track Car",
            car_type="coupe",
            order_reference_status=CarOrderReferenceStatus(
                selection_source_status="manual_entry",
                tire_dimensions_confidence="user_confirmed",
                final_drive_ratio_confidence="user_confirmed",
                current_gear_ratio_confidence="user_confirmed",
                transmission_name="8-speed automatic",
                transmission_confidence="official_exact",
            ),
        ),
    )

    assert metadata.car == RunCarMetadata(
        car_id="car-1",
        name="Track Car",
        car_type="coupe",
        order_reference_status=CarOrderReferenceStatus(
            selection_source_status="manual_entry",
            tire_dimensions_confidence="user_confirmed",
            final_drive_ratio_confidence="user_confirmed",
            current_gear_ratio_confidence="user_confirmed",
            transmission_name="8-speed automatic",
            transmission_confidence="official_exact",
        ),
    )


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
        def _get(cid: str) -> MagicMock:
            record = MagicMock()
            record.firmware_version = {"c1": "1.0.0", "c2": "2.0.0"}[cid]
            return record

        reg = MagicMock()
        reg.active_client_ids.return_value = ["c1", "c2"]
        reg.get.side_effect = _get
        assert firmware_version_for_run(reg) == "1.0.0, 2.0.0"

    def test_blank_and_missing_versions_are_ignored(self) -> None:
        def _get(cid: str) -> MagicMock:
            record = MagicMock()
            record.firmware_version = {"c1": " ", "c2": None}.get(cid)
            return record

        reg = MagicMock()
        reg.active_client_ids.return_value = ["c1", "c2"]
        reg.get.side_effect = _get
        assert firmware_version_for_run(reg) is None


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
