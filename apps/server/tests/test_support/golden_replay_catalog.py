"""Fixture catalog for golden replay calibration scenarios."""

from __future__ import annotations

from test_support.core import FINAL_DRIVE, wheel_hz
from test_support.golden_replay import GoldenReplayExpected, GoldenReplayFixture

_DEFAULT_SPEED_KMH = 80.0
_DEFAULT_ENGINE_RPM = 1500.0
_DRIVESHAFT_SOURCE = "driveline"
_ENGINE_SOURCE = "engine"
_WHEEL_SOURCE = "wheel/tire"


def golden_replay_fixture_catalog() -> tuple[GoldenReplayFixture, ...]:
    return (
        _balanced_fixture(),
        _front_wheel_fixture(),
        _rear_wheel_fixture(),
        _driveshaft_fixture(),
        _engine_fixture(),
        _fixed_resonance_fixture(),
        _road_shock_fixture(),
        _transient_fixture(),
        _noisy_sensor_fixture(),
        _gps_dropout_fixture(),
        _missing_rpm_fixture(),
    )


def _balanced_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="balanced-no-issue",
        title="Balanced/no issue",
        group="baseline",
        seed=1001,
        primary_frequency_hz=None,
        strongest_sensor=None,
        engine_rpm=None,
        expected=GoldenReplayExpected(
            suspected_source=None,
            confidence_range=(0.0, 0.35),
            max_false_positive_confidence=0.35,
            required_warning_codes=("reference_context_incomplete",),
            tolerance_bands={"top_confidence": (0.0, 0.35)},
        ),
    )


def _front_wheel_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="front-wheel-imbalance",
        title="Front wheel imbalance",
        group="wheel",
        seed=1002,
        primary_frequency_hz=wheel_hz(_DEFAULT_SPEED_KMH),
        strongest_sensor="front-left",
        expected=GoldenReplayExpected(
            suspected_source=_WHEEL_SOURCE,
            strongest_location="front-left",
            confidence_range=(0.45, 0.9),
            confidence_label_key="CONFIDENCE_MEDIUM",
            tolerance_bands={"frequency_hz": (9.0, 12.0), "top_confidence": (0.45, 0.9)},
        ),
    )


def _rear_wheel_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="rear-wheel-imbalance",
        title="Rear wheel imbalance",
        group="wheel",
        seed=1003,
        primary_frequency_hz=wheel_hz(_DEFAULT_SPEED_KMH),
        strongest_sensor="rear-right",
        expected=GoldenReplayExpected(
            suspected_source=_WHEEL_SOURCE,
            strongest_location="rear-right",
            confidence_range=(0.45, 0.9),
            confidence_label_key="CONFIDENCE_MEDIUM",
            tolerance_bands={"frequency_hz": (9.0, 12.0), "top_confidence": (0.45, 0.9)},
        ),
    )


def _driveshaft_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="driveshaft-rumble",
        title="Driveshaft rumble",
        group="driveline",
        seed=1004,
        primary_frequency_hz=wheel_hz(_DEFAULT_SPEED_KMH) * FINAL_DRIVE,
        strongest_sensor="rear-left",
        expected=GoldenReplayExpected(
            suspected_source=_DRIVESHAFT_SOURCE,
            strongest_location="rear-left",
            confidence_range=(0.4, 0.9),
            confidence_label_key="CONFIDENCE_MEDIUM",
            tolerance_bands={"frequency_hz": (29.0, 34.0), "top_confidence": (0.4, 0.9)},
        ),
    )


def _engine_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="engine-harmonic",
        title="Engine harmonic",
        group="engine",
        seed=1005,
        primary_frequency_hz=_DEFAULT_ENGINE_RPM / 60.0,
        strongest_sensor="front-left",
        expected=GoldenReplayExpected(
            suspected_source=_ENGINE_SOURCE,
            strongest_location="front-left",
            confidence_range=(0.4, 0.9),
            confidence_label_key="CONFIDENCE_MEDIUM",
            tolerance_bands={"frequency_hz": (23.0, 27.0), "top_confidence": (0.4, 0.9)},
        ),
    )


def _fixed_resonance_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="fixed-resonance-speed-sweep",
        title="Fixed resonance during speed sweep",
        group="resonance",
        seed=1006,
        primary_frequency_hz=67.0,
        strongest_sensor="front-right",
        signal_amp_g=0.04,
        transfer_amp_g=0.012,
        speed_kmh=None,
        speed_sweep_kmh=(45.0, 115.0),
        expected=GoldenReplayExpected(
            suspected_source=None,
            confidence_range=(0.0, 0.45),
            max_false_positive_confidence=0.45,
            tolerance_bands={
                "fixed_frequency_hz": (66.0, 68.0),
                "top_confidence": (0.0, 0.45),
            },
        ),
    )


def _road_shock_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="road-shock-transient",
        title="Road shock transient",
        group="road_shock",
        seed=1007,
        primary_frequency_hz=None,
        strongest_sensor="front-left",
        signal_amp_g=0.12,
        transfer_amp_g=0.006,
        engine_rpm=None,
        final_drive_ratio=None,
        current_gear_ratio=None,
        transient_duration_s=2.0,
        transient_frequency_hz=50.0,
        expected=GoldenReplayExpected(
            suspected_source=None,
            confidence_range=(0.0, 0.45),
            max_false_positive_confidence=0.45,
            tolerance_bands={"top_confidence": (0.0, 0.45)},
            required_metadata_minimums={"whole_run_spectral_quality_limited_window_count": 1.0},
        ),
    )


def _transient_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="transient-spike",
        title="Transient spike",
        group="transient",
        seed=1008,
        primary_frequency_hz=None,
        strongest_sensor="front-left",
        signal_amp_g=0.12,
        transfer_amp_g=0.006,
        engine_rpm=None,
        final_drive_ratio=None,
        current_gear_ratio=None,
        transient_duration_s=2.0,
        transient_frequency_hz=50.0,
        expected=GoldenReplayExpected(
            suspected_source=None,
            confidence_range=(0.0, 0.45),
            max_false_positive_confidence=0.45,
            tolerance_bands={"top_confidence": (0.0, 0.45)},
        ),
    )


def _noisy_sensor_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="noisy-sensor",
        title="Noisy sensor",
        group="data_quality",
        seed=1009,
        primary_frequency_hz=None,
        strongest_sensor="front-right",
        signal_amp_g=0.018,
        transfer_amp_g=0.006,
        expected=GoldenReplayExpected(
            suspected_source=None,
            confidence_range=(0.0, 0.45),
            max_false_positive_confidence=0.45,
            tolerance_bands={"top_confidence": (0.0, 0.45)},
        ),
    )


def _gps_dropout_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="gps-dropout",
        title="GPS dropout",
        group="data_quality",
        seed=1010,
        primary_frequency_hz=wheel_hz(_DEFAULT_SPEED_KMH),
        strongest_sensor="front-left",
        speed_source="gps_unaligned",
        expected=GoldenReplayExpected(
            suspected_source=_WHEEL_SOURCE,
            strongest_location="front-left",
            confidence_range=(0.35, 0.9),
            unavailable_reasons=("missing_speed",),
            tolerance_bands={"missing_speed_windows_min": (1.0, 9999.0)},
        ),
    )


def _missing_rpm_fixture() -> GoldenReplayFixture:
    return GoldenReplayFixture(
        case_id="missing-rpm",
        title="Missing RPM",
        group="data_quality",
        seed=1011,
        primary_frequency_hz=_DEFAULT_ENGINE_RPM / 60.0,
        strongest_sensor="front-left",
        engine_rpm=None,
        final_drive_ratio=None,
        current_gear_ratio=None,
        expected=GoldenReplayExpected(
            suspected_source=None,
            confidence_range=(0.0, 0.45),
            unavailable_reasons=("missing_rpm",),
            max_false_positive_confidence=0.45,
            tolerance_bands={"missing_rpm_windows_min": (1.0, 9999.0)},
        ),
    )
