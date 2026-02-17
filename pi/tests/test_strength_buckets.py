from __future__ import annotations

from vibesensor.analysis.strength_metrics import strength_db
from vibesensor.diagnostics_shared import severity_from_peak


def test_strength_db_maps_to_expected_bucket() -> None:
    state = None
    out = None
    for _ in range(3):
        out = severity_from_peak(strength_db=23.0, band_rms=0.02, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or {})
    assert out is not None
    assert out["key"] == "l3"


def test_persistence_and_decay_behavior() -> None:
    state = None
    out = None
    # Promote to L2 after persistence ticks.
    for _ in range(3):
        out = severity_from_peak(
            strength_db=17.0, band_rms=0.007, sensor_count=1, prior_state=state
        )
        state = dict(out.get("state") or state or {})
    assert out is not None
    assert out["key"] == "l2"

    # Short dip should not demote due to decay requirement.
    for _ in range(4):
        out = severity_from_peak(strength_db=5.0, band_rms=0.0, sensor_count=1, prior_state=state)
        state = dict((out or {}).get("state") or state or {})
    assert out is not None
    assert out["key"] == "l2"

    # Fifth decay tick demotes.
    out = severity_from_peak(strength_db=5.0, band_rms=0.0, sensor_count=1, prior_state=state)
    assert out is not None
    assert out["key"] is None


def test_eps_behavior_floor_zero_is_finite() -> None:
    db = strength_db(
        strength_peak_band_rms_amp_g=1e-6,
        strength_floor_amp_g=0.0,
    )
    assert db > 0
    assert db < 100
