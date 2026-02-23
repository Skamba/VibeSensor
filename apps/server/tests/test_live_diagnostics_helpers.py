from __future__ import annotations

from vibesensor.live_diagnostics import (
    SEVERITY_KEYS,
    SOURCE_KEYS,
    LiveDiagnosticsEngine,
    _copy_matrix,
    _new_matrix,
)

# -- _new_matrix ---------------------------------------------------------------


def test_new_matrix_structure() -> None:
    m = _new_matrix()
    assert set(m.keys()) == set(SOURCE_KEYS)
    for source in SOURCE_KEYS:
        assert set(m[source].keys()) == set(SEVERITY_KEYS)
        for severity in SEVERITY_KEYS:
            cell = m[source][severity]
            assert cell["count"] == 0
            assert cell["seconds"] == 0.0
            assert cell["contributors"] == {}


# -- _copy_matrix --------------------------------------------------------------


def test_copy_matrix_is_deep() -> None:
    m = _new_matrix()
    m["engine"]["l1"]["count"] = 5
    m["engine"]["l1"]["contributors"]["sensor_a"] = 3
    copy = _copy_matrix(m)
    assert copy["engine"]["l1"]["count"] == 5
    assert copy["engine"]["l1"]["contributors"]["sensor_a"] == 3
    # Mutating copy should not affect original
    copy["engine"]["l1"]["count"] = 99
    assert m["engine"]["l1"]["count"] == 5


# -- LiveDiagnosticsEngine.reset -----------------------------------------------


def test_engine_reset_clears_state() -> None:
    engine = LiveDiagnosticsEngine()
    engine.reset()
    snap = engine.snapshot()
    assert snap["events"] == []
    assert snap["findings"] == []
    # Matrix should be all zeros
    for source in SOURCE_KEYS:
        for severity in SEVERITY_KEYS:
            assert snap["matrix"][source][severity]["count"] == 0


# -- LiveDiagnosticsEngine.snapshot structure ----------------------------------


def test_engine_snapshot_has_expected_keys() -> None:
    engine = LiveDiagnosticsEngine()
    snap = engine.snapshot()
    assert "diagnostics_sequence" in snap
    assert "matrix" in snap
    assert "events" in snap
    assert "strength_bands" in snap
    assert "levels" in snap
    assert "by_source" in snap["levels"]
    assert "by_sensor" in snap["levels"]
    assert "by_location" in snap["levels"]
    assert "findings" in snap
    assert "top_finding" in snap


# -- LiveDiagnosticsEngine._should_emit_event ----------------------------------


def test_should_emit_on_new_bucket() -> None:
    from vibesensor.live_diagnostics import _TrackerLevelState

    engine = LiveDiagnosticsEngine()
    tracker = _TrackerLevelState()
    assert (
        engine._should_emit_event(
            tracker=tracker, previous_bucket=None, current_bucket="l1", now_ms=1000
        )
        is True
    )


def test_should_not_emit_on_no_bucket() -> None:
    from vibesensor.live_diagnostics import _TrackerLevelState

    engine = LiveDiagnosticsEngine()
    tracker = _TrackerLevelState()
    assert (
        engine._should_emit_event(
            tracker=tracker, previous_bucket=None, current_bucket=None, now_ms=1000
        )
        is False
    )


def test_should_emit_on_escalation() -> None:
    from vibesensor.live_diagnostics import _TrackerLevelState

    engine = LiveDiagnosticsEngine()
    tracker = _TrackerLevelState()
    assert (
        engine._should_emit_event(
            tracker=tracker, previous_bucket="l1", current_bucket="l3", now_ms=1000
        )
        is True
    )


# -- _matrix_transition_bucket -------------------------------------------------


def test_matrix_transition_new_bucket() -> None:
    engine = LiveDiagnosticsEngine()
    assert engine._matrix_transition_bucket(None, "l1") == "l1"


def test_matrix_transition_escalation() -> None:
    engine = LiveDiagnosticsEngine()
    assert engine._matrix_transition_bucket("l1", "l3") == "l3"


def test_matrix_transition_same_level_returns_none() -> None:
    engine = LiveDiagnosticsEngine()
    assert engine._matrix_transition_bucket("l2", "l2") is None


def test_matrix_transition_downgrade_returns_none() -> None:
    engine = LiveDiagnosticsEngine()
    assert engine._matrix_transition_bucket("l3", "l1") is None


def test_matrix_transition_none_current_returns_none() -> None:
    engine = LiveDiagnosticsEngine()
    assert engine._matrix_transition_bucket("l2", None) is None


def test_findings_language_is_forwarded(monkeypatch) -> None:
    engine = LiveDiagnosticsEngine()
    seen: dict[str, str] = {}

    def _fake_build_findings_for_samples(*, metadata, samples, lang):  # type: ignore[no-untyped-def]
        seen["lang"] = lang
        return []

    monkeypatch.setattr(
        "vibesensor.live_diagnostics.build_findings_for_samples",
        _fake_build_findings_for_samples,
    )
    engine.update(
        speed_mps=0.0,
        clients=[],
        spectra=None,
        settings={},
        finding_metadata={},
        finding_samples=[],
        language="nl",
    )
    assert seen["lang"] == "nl"


# -- LiveDiagnosticsEngine driving phase tracking --------------------------------


def test_snapshot_includes_driving_phase_key() -> None:
    engine = LiveDiagnosticsEngine()
    snap = engine.snapshot()
    assert "driving_phase" in snap


def test_initial_driving_phase_is_idle() -> None:
    engine = LiveDiagnosticsEngine()
    snap = engine.snapshot()
    assert snap["driving_phase"] == "idle"


def test_driving_phase_idle_when_speed_zero(monkeypatch) -> None:
    t = {"value": 0.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["value"])
    engine = LiveDiagnosticsEngine()
    for i in range(3):
        t["value"] = float(i)
        engine.update(speed_mps=0.0, clients=[], spectra=None, settings={})
    snap = engine.snapshot()
    assert snap["driving_phase"] == "idle"


def test_driving_phase_speed_unknown_when_speed_none(monkeypatch) -> None:
    t = {"value": 0.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["value"])
    engine = LiveDiagnosticsEngine()
    for i in range(3):
        t["value"] = float(i)
        engine.update(speed_mps=None, clients=[], spectra=None, settings={})
    snap = engine.snapshot()
    assert snap["driving_phase"] == "speed_unknown"


def test_driving_phase_cruise_at_constant_speed(monkeypatch) -> None:
    t = {"value": 0.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["value"])
    engine = LiveDiagnosticsEngine()
    # Constant 50 km/h → cruise
    speed_mps = 50.0 / 3.6
    for i in range(5):
        t["value"] = float(i)
        engine.update(speed_mps=speed_mps, clients=[], spectra=None, settings={})
    snap = engine.snapshot()
    assert snap["driving_phase"] == "cruise"


def test_driving_phase_acceleration_detected(monkeypatch) -> None:
    t = {"value": 0.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["value"])
    engine = LiveDiagnosticsEngine()
    # Speed ramps from 30 → 60 km/h over 5 seconds = +6 km/h/s, well above 1.5 threshold
    speeds_kmh = [30.0, 36.0, 42.0, 48.0, 54.0, 60.0]
    for i, s in enumerate(speeds_kmh):
        t["value"] = float(i)
        engine.update(speed_mps=s / 3.6, clients=[], spectra=None, settings={})
    snap = engine.snapshot()
    assert snap["driving_phase"] == "acceleration"


def test_driving_phase_deceleration_detected(monkeypatch) -> None:
    t = {"value": 0.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["value"])
    engine = LiveDiagnosticsEngine()
    # Speed drops from 80 → 50 km/h over 5 seconds = -6 km/h/s, well below -1.5 threshold
    speeds_kmh = [80.0, 74.0, 68.0, 62.0, 56.0, 50.0]
    for i, s in enumerate(speeds_kmh):
        t["value"] = float(i)
        engine.update(speed_mps=s / 3.6, clients=[], spectra=None, settings={})
    snap = engine.snapshot()
    assert snap["driving_phase"] == "deceleration"


def test_driving_phase_reset_clears_to_idle(monkeypatch) -> None:
    t = {"value": 0.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["value"])
    engine = LiveDiagnosticsEngine()
    speed_mps = 50.0 / 3.6
    for i in range(5):
        t["value"] = float(i)
        engine.update(speed_mps=speed_mps, clients=[], spectra=None, settings={})
    assert engine.snapshot()["driving_phase"] == "cruise"
    engine.reset()
    assert engine.snapshot()["driving_phase"] == "idle"


def test_driving_phase_tracked_on_spectra_none_path(monkeypatch) -> None:
    """Phase update must occur even on the light-tick spectra=None path."""
    t = {"value": 0.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["value"])
    engine = LiveDiagnosticsEngine()
    speed_mps = 50.0 / 3.6
    for i in range(5):
        t["value"] = float(i)
        snap = engine.update(speed_mps=speed_mps, clients=[], spectra=None, settings={})
    assert snap["driving_phase"] == "cruise"
