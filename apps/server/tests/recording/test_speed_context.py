"""Speed context resolution: speed source, GPS speed and engine RPM."""

from __future__ import annotations

import pytest

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.recording.sample_speed_context import (
    resolve_speed_context,
    resolve_speed_context_snapshot,
)
from vibesensor.speed.aligned_speed_context import AlignedSpeedContextSnapshot


def _analysis_settings_snapshot(
    *, current_gear_ratio: float | None = 1.0
) -> AnalysisSettingsSnapshot:
    payload: dict[str, float] = {
        "tire_width_mm": 205,
        "tire_aspect_pct": 55,
        "rim_in": 16,
        "final_drive_ratio": 3.73,
    }
    if current_gear_ratio is not None:
        payload["current_gear_ratio"] = current_gear_ratio
    return AnalysisSettingsSnapshot(**payload)


@pytest.mark.parametrize(
    ("gps_speed_mps", "resolved_speed_mps", "source", "speed_kmh", "gps_speed_kmh"),
    [
        pytest.param(None, None, "none", None, None, id="no-speed"),
        pytest.param(10.0, 10.0, "gps", 36.0, 36.0, id="gps"),
        pytest.param(10.0, 20.0, "manual", 72.0, 36.0, id="manual-override"),
        pytest.param(None, 20.0, "fallback_manual", 72.0, None, id="fallback-manual"),
    ],
)
def test_speed_source_and_speeds_follow_the_resolution(
    gps_speed_mps: float | None,
    resolved_speed_mps: float | None,
    source: str,
    speed_kmh: float | None,
    gps_speed_kmh: float | None,
) -> None:
    context = resolve_speed_context(
        gps_speed_mps=gps_speed_mps,
        resolved_speed_mps=resolved_speed_mps,
        resolved_speed_source=source,
        analysis_settings_snapshot=_analysis_settings_snapshot(),
    )

    assert context.speed_source == source
    assert context.speed_kmh == (None if speed_kmh is None else pytest.approx(speed_kmh))
    assert context.gps_speed_kmh == (
        None if gps_speed_kmh is None else pytest.approx(gps_speed_kmh)
    )
    if speed_kmh is None:
        assert (context.engine_rpm, context.engine_rpm_source) == (None, "missing")
    else:
        assert context.engine_rpm is not None and context.engine_rpm > 0
        assert context.engine_rpm_source == "estimated_from_speed_and_ratios"


def test_engine_rpm_is_estimated_from_the_order_reference() -> None:
    # 205/55 R16, no deflection: 0.6322 m diameter -> 1.986 m circumference.
    # 36 km/h -> 5.034 wheel Hz x 3.73 final drive x 1.0 gear -> 1126.6 rpm.
    context = resolve_speed_context(
        gps_speed_mps=10.0,
        resolved_speed_mps=10.0,
        resolved_speed_source="gps",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
    )
    assert context.engine_rpm == pytest.approx(1126.6, rel=0.01)


def test_missing_gear_ratio_skips_the_rpm_estimate() -> None:
    context = resolve_speed_context(
        gps_speed_mps=15.0,
        resolved_speed_mps=15.0,
        resolved_speed_source="gps",
        analysis_settings_snapshot=_analysis_settings_snapshot(current_gear_ratio=None),
    )
    assert (context.engine_rpm, context.engine_rpm_source) == (None, "missing")


def test_measured_engine_rpm_takes_precedence_over_estimate() -> None:
    context = resolve_speed_context(
        gps_speed_mps=12.0,
        resolved_speed_mps=12.0,
        resolved_speed_source="obd2",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        measured_engine_rpm=3210.0,
        measured_engine_rpm_source="obd2_pid",
    )

    assert context.speed_kmh == pytest.approx(43.2)
    assert context.engine_rpm == 3210.0
    assert context.engine_rpm_source == "obd2_pid"


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
        analysis_settings_snapshot=_analysis_settings_snapshot(),
    )

    assert context.speed_kmh == pytest.approx(72.0, rel=0.01)
    assert context.speed_source == "fallback_manual"
    assert context.engine_rpm is not None and context.engine_rpm > 0.0
    assert context.engine_rpm_source == "estimated_from_speed_and_ratios"
