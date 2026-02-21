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
    assert "matrix" in snap
    assert "events" in snap
    assert "strength_bands" in snap
    assert "levels" in snap
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
