"""Direct behavior tests for speed context resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig
from vibesensor.use_cases.run.sample_speed_context import (
    resolve_speed_context,
    resolve_speed_context_snapshot,
)


def _make_run_recorder() -> tuple[RunRecorder, MagicMock]:
    gps_mock = MagicMock()
    gps_mock.speed_mps = None
    gps_mock.effective_speed_mps = None
    gps_mock.override_speed_mps = None
    gps_mock.resolve_speed.return_value = MagicMock(source="none")

    registry = MagicMock()
    registry.active_client_ids.return_value = []

    settings_mock = MagicMock()
    settings_mock.analysis_settings_snapshot.return_value = AnalysisSettingsSnapshot(
        tire_width_mm=205,
        tire_aspect_pct=55,
        rim_in=16,
        final_drive_ratio=3.73,
        current_gear_ratio=1.0,
    )

    logger = RunRecorder(
        RunRecorderConfig(
            metrics_log_hz=1,
            sensor_model="test",
            default_sample_rate_hz=800,
            fft_window_size_samples=512,
            persist_history_db=False,
        ),
        registry=registry,
        gps_monitor=gps_mock,
        processor=MagicMock(),
        settings_reader=settings_mock,
    )
    return logger, gps_mock


class TestResolveSpeedContext:
    """Tests for resolve_speed_context via a minimal RunRecorder setup."""

    @staticmethod
    def _resolve_from_logger(
        logger,
    ) -> tuple[float | None, float | None, str, float | None, str]:
        resolution = logger.gps_monitor.resolve_speed()
        return resolve_speed_context(
            gps_speed_mps=logger.gps_monitor.speed_mps,
            resolved_speed_mps=resolution.speed_mps,
            resolved_speed_source=resolution.source,
            analysis_settings_snapshot=logger._analysis_settings_snapshot(),
        )

    def test_no_speed_available(self) -> None:
        logger, _ = _make_run_recorder()
        speed_kmh, gps_speed, source, rpm, rpm_source = self._resolve_from_logger(logger)
        assert speed_kmh is None
        assert gps_speed is None
        assert source == "none"
        assert rpm is None
        assert rpm_source == "missing"

    def test_gps_speed_available(self) -> None:
        logger, gps_mock = _make_run_recorder()
        gps_mock.speed_mps = 10.0
        gps_mock.resolve_speed.return_value = MagicMock(source="gps", speed_mps=10.0)
        speed_kmh, gps_speed, source, rpm, rpm_source = self._resolve_from_logger(logger)
        assert speed_kmh == pytest.approx(36.0, rel=0.01)
        assert gps_speed == pytest.approx(36.0, rel=0.01)
        assert source == "gps"
        assert rpm is not None and rpm > 0
        assert rpm_source == "estimated_from_speed_and_ratios"

    def test_manual_override(self) -> None:
        logger, gps_mock = _make_run_recorder()
        gps_mock.override_speed_mps = 20.0
        gps_mock.resolve_speed.return_value = MagicMock(source="manual", speed_mps=20.0)
        speed_kmh, _, source, _, _ = self._resolve_from_logger(logger)
        assert speed_kmh == pytest.approx(72.0, rel=0.01)
        assert source == "manual"

    def test_fallback_manual_override_preserves_distinct_source(self) -> None:
        logger, gps_mock = _make_run_recorder()
        gps_mock.override_speed_mps = 20.0
        gps_mock.resolve_speed.return_value = MagicMock(source="fallback_manual", speed_mps=20.0)
        speed_kmh, _, source, _, _ = self._resolve_from_logger(logger)
        assert speed_kmh == pytest.approx(72.0, rel=0.01)
        assert source == "fallback_manual"

    def test_no_gear_ratio_skips_rpm(self) -> None:
        logger, gps_mock = _make_run_recorder()
        gps_mock.resolve_speed.return_value = MagicMock(source="gps", speed_mps=15.0)
        settings_mock = logger._settings_reader
        settings_mock.analysis_settings_snapshot.return_value = AnalysisSettingsSnapshot(
            tire_width_mm=205,
            tire_aspect_pct=55,
            rim_in=16,
            final_drive_ratio=3.73,
        )
        _, _, _, rpm, rpm_source = self._resolve_from_logger(logger)
        assert rpm is None
        assert rpm_source == "missing"

    def test_uses_order_reference_spec_for_engine_rpm(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _FakeSpec:
            def engine_rpm_from_speed_kmh(self, speed_kmh: float) -> float | None:
                return 1234.5 if speed_kmh > 0 else None

        monkeypatch.setattr(
            "vibesensor.use_cases.run.sample_speed_context.order_reference_spec_from_snapshot",
            lambda snapshot: _FakeSpec(),
        )
        logger, gps_mock = _make_run_recorder()
        gps_mock.speed_mps = 10.0
        gps_mock.resolve_speed.return_value = MagicMock(source="gps", speed_mps=10.0)

        speed, _, _, rpm, rpm_source = self._resolve_from_logger(logger)

        assert speed == pytest.approx(36.0, rel=0.01)
        assert rpm == 1234.5
        assert rpm_source == "estimated_from_speed_and_ratios"


def test_resolve_speed_context_snapshot_preserves_fallback_manual_source() -> None:
    snapshot = AlignedSpeedContextSnapshot(
        selected_speed_source="gps",
        resolved_speed_mps=20.0,
        resolved_speed_source="fallback_manual",
        resolved_speed_aligned=True,
        gps_speed_mps=None,
        gps_speed_aligned=False,
        measured_engine_rpm=None,
        measured_engine_rpm_source=None,
        measured_engine_rpm_aligned=False,
    )

    context = resolve_speed_context_snapshot(
        snapshot=snapshot,
        analysis_settings_snapshot=AnalysisSettingsSnapshot(
            tire_width_mm=205,
            tire_aspect_pct=55,
            rim_in=16,
            final_drive_ratio=3.73,
            current_gear_ratio=1.0,
        ),
    )

    assert context.speed_kmh == pytest.approx(72.0, rel=0.01)
    assert context.speed_source == "fallback_manual"
    assert context.engine_rpm is not None and context.engine_rpm > 0.0
    assert context.engine_rpm_source == "estimated_from_speed_and_ratios"
