from __future__ import annotations

from vibesensor.severity import severity_from_peak
from vibesensor.vibration_strength import vibration_strength_db_scalar


def _run_severity_ticks(
    db: float,
    ticks: int,
    state: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Run *ticks* iterations of ``severity_from_peak`` and return (last_out, state)."""
    out: dict[str, object] | None = None
    for _ in range(ticks):
        out = severity_from_peak(vibration_strength_db=db, sensor_count=1, prior_state=state)
        state = dict(out.get("state") or state or {})  # type: ignore[arg-type]
    assert out is not None
    return out, state


def test_strength_db_maps_to_expected_bucket() -> None:
    out, _ = _run_severity_ticks(db=27.0, ticks=3)
    assert out["key"] == "l3"


def test_persistence_and_decay_behavior() -> None:
    # Promote to L2 after persistence ticks.
    out, state = _run_severity_ticks(db=17.0, ticks=3)
    assert out["key"] == "l2"

    # Short dip should not demote due to decay requirement.
    out, state = _run_severity_ticks(db=5.0, ticks=4, state=state)
    assert out["key"] == "l2"

    # Fifth decay tick demotes.
    out, _ = _run_severity_ticks(db=5.0, ticks=1, state=state)
    assert out["key"] is None


def test_eps_behavior_floor_zero_is_finite() -> None:
    db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=1e-6,
        floor_amp_g=0.0,
    )
    assert db > 0
    assert db < 100
