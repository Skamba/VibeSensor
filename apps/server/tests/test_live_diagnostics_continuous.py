from __future__ import annotations

import math
from types import MethodType

import pytest
from vibesensor_core.strength_bands import DECAY_TICKS, HYSTERESIS_DB, band_by_key
from vibesensor_core.vibration_strength import compute_vibration_strength_db

from vibesensor.constants import SILENCE_DB
from vibesensor.diagnostics_shared import severity_from_peak
from vibesensor.live_diagnostics import LiveDiagnosticsEngine, _RecentEvent, _TrackerLevelState


def test_severity_holds_for_small_hysteresis_dip_then_decays() -> None:
    state = None
    out = None
    for _ in range(3):
        out = severity_from_peak(vibration_strength_db=27.0, sensor_count=1, prior_state=state)
        state = dict((out or {}).get("state") or {})
    assert out is not None
    assert out["key"] == "l3"

    l3 = band_by_key("l3")
    assert l3 is not None
    slight_dip = float(l3["min_db"]) - (HYSTERESIS_DB / 2)
    out = severity_from_peak(vibration_strength_db=slight_dip, sensor_count=1, prior_state=state)
    state = dict((out or {}).get("state") or state or {})
    assert out is not None
    assert out["key"] == "l3"

    for _ in range(DECAY_TICKS):
        out = severity_from_peak(
            vibration_strength_db=SILENCE_DB, sensor_count=1, prior_state=state
        )
        state = dict((out or {}).get("state") or state or {})
    assert out is not None
    assert out["key"] is None


def test_severity_frequency_hopping_does_not_promote_within_persistence_ticks() -> None:
    state = None
    out = None
    for peak_hz in (25.0, 80.0, 25.0):
        out = severity_from_peak(
            vibration_strength_db=27.0,
            sensor_count=1,
            prior_state=state,
            peak_hz=peak_hz,
            persistence_freq_bin_hz=1.5,
        )
        state = dict((out or {}).get("state") or {})
    assert out is not None
    assert out["key"] is None


def test_severity_stable_frequency_promotes_within_persistence_ticks() -> None:
    state = None
    out = None
    for _ in range(3):
        out = severity_from_peak(
            vibration_strength_db=27.0,
            sensor_count=1,
            prior_state=state,
            peak_hz=25.0,
            persistence_freq_bin_hz=1.5,
        )
        state = dict((out or {}).get("state") or {})
    assert out is not None
    assert out["key"] == "l3"


def test_live_matrix_seconds_use_recent_window_during_throttled_emission(monkeypatch) -> None:
    current_s = {"value": 10.0}

    def fake_monotonic() -> float:
        return current_s["value"]

    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", fake_monotonic)

    engine = LiveDiagnosticsEngine()
    settings = {}
    speed_mps = 27.8
    freq = [idx * 0.1 for idx in range(1, 1200)]
    peak_idx = 320
    base = [0.8 for _ in freq]
    base[peak_idx] = 150.0
    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq,
        combined_spectrum_amp_g_values=base,
        peak_bandwidth_hz=1.2,
        peak_separation_hz=1.2,
        top_n=5,
    )
    spectra = {
        "freq": freq,
        "clients": {
            "c1": {
                "freq": freq,
                "x": base,
                "y": base,
                "z": base,
                "combined_spectrum_amp_g": base,
                "strength_metrics": strength_metrics,
            }
        },
    }

    snapshots = []
    for _ in range(12):
        snapshots.append(
            engine.update(
                speed_mps=speed_mps,
                clients=[{"id": "c1", "name": "front"}],
                spectra=spectra,
                settings=settings,
            )
        )
        current_s["value"] += 1.0

    final = snapshots[-1]
    max_seconds = max(
        float(cell["seconds"])
        for source_row in final["matrix"].values()
        for cell in source_row.values()
    )
    # Live matrix is intentionally windowed for UI readability; it should stay bounded.
    assert 0.0 < max_seconds <= 3.0

    emitted = sum(len(snapshot.get("events") or []) for snapshot in snapshots)
    assert emitted < len(snapshots)


def test_events_persist_when_spectra_is_none(monkeypatch) -> None:
    """Events should not be cleared on light ticks (spectra=None)."""
    current_s = {"value": 10.0}

    def fake_monotonic() -> float:
        return current_s["value"]

    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", fake_monotonic)

    engine = LiveDiagnosticsEngine()
    freq = [idx * 0.1 for idx in range(1, 1200)]
    peak_idx = 320
    base = [0.8 for _ in freq]
    base[peak_idx] = 150.0
    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq,
        combined_spectrum_amp_g_values=base,
        peak_bandwidth_hz=1.2,
        peak_separation_hz=1.2,
        top_n=5,
    )
    spectra = {
        "freq": freq,
        "clients": {
            "c1": {
                "freq": freq,
                "x": base,
                "y": base,
                "z": base,
                "combined_spectrum_amp_g": base,
                "strength_metrics": strength_metrics,
            }
        },
    }

    # Several heavy ticks to build up tracker state and emit events
    snap_heavy = None
    for _ in range(6):
        current_s["value"] += 1.0
        snap_heavy = engine.update(
            speed_mps=27.8,
            clients=[{"id": "c1", "name": "front"}],
            spectra=spectra,
            settings={},
        )
    assert snap_heavy is not None
    assert len(snap_heavy["events"]) > 0, "Heavy ticks should eventually emit events"
    events_after_heavy = list(snap_heavy["events"])

    # Light tick: spectra=None should preserve events
    current_s["value"] += 0.1
    snap_light = engine.update(
        speed_mps=27.8,
        clients=[{"id": "c1", "name": "front"}],
        spectra=None,
        settings={},
    )
    assert snap_light["events"] == events_after_heavy, (
        "Light tick should preserve events from previous heavy tick"
    )

    # Another light tick: events still preserved
    current_s["value"] += 0.1
    snap_light2 = engine.update(
        speed_mps=27.8,
        clients=[{"id": "c1", "name": "front"}],
        spectra=None,
        settings={},
    )
    assert snap_light2["events"] == events_after_heavy, (
        "Second light tick should still preserve events"
    )


def test_matrix_preserved_when_spectra_is_none(monkeypatch) -> None:
    """Matrix counts should not be lost on light ticks;
    dwell seconds should continue to accumulate."""
    current_s = {"value": 10.0}

    def fake_monotonic() -> float:
        return current_s["value"]

    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", fake_monotonic)

    engine = LiveDiagnosticsEngine()
    freq = [idx * 0.1 for idx in range(1, 1200)]
    peak_idx = 320
    base = [0.8 for _ in freq]
    base[peak_idx] = 150.0
    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq,
        combined_spectrum_amp_g_values=base,
        peak_bandwidth_hz=1.2,
        peak_separation_hz=1.2,
        top_n=5,
    )
    spectra = {
        "freq": freq,
        "clients": {
            "c1": {
                "freq": freq,
                "x": base,
                "y": base,
                "z": base,
                "combined_spectrum_amp_g": base,
                "strength_metrics": strength_metrics,
            }
        },
    }

    # Several heavy ticks to accumulate matrix (small time steps to stay inside window)
    for _ in range(5):
        current_s["value"] += 0.2
        engine.update(
            speed_mps=27.8,
            clients=[{"id": "c1", "name": "front"}],
            spectra=spectra,
            settings={},
        )

    snap_before = engine.snapshot()
    matrix_before = snap_before["matrix"]

    # Collect any non-zero seconds from before
    total_seconds_before = sum(
        cell["seconds"]
        for cols in matrix_before.values()
        for cell in cols.values()
    )

    # Light tick should preserve matrix structure and continue accumulating dwell seconds
    current_s["value"] += 0.1
    snap_after = engine.update(
        speed_mps=27.8,
        clients=[{"id": "c1", "name": "front"}],
        spectra=None,
        settings={},
    )
    matrix_after = snap_after["matrix"]

    # Matrix structure is preserved
    assert set(matrix_after.keys()) == set(matrix_before.keys())
    for source in matrix_before:
        assert set(matrix_after[source].keys()) == set(matrix_before[source].keys())

    # Dwell seconds should be >= before (they accumulate on light ticks now)
    total_seconds_after = sum(
        cell["seconds"]
        for cols in matrix_after.values()
        for cell in cols.values()
    )
    assert total_seconds_after >= total_seconds_before, (
        "Matrix dwell seconds should not decrease on light tick"
    )


def test_combined_multi_sensor_strength_uses_linear_amplitude_domain(monkeypatch) -> None:
    """Averaging dB values directly is mathematically wrong for amplitude-derived metrics.

    For amplitude dB values, each sensor must be converted to a linear amplitude ratio before
    combining. The correct combined dB is `20*log10(mean(10**(db/20)))`, not `mean(db)`.
    This test fixes the contract for combined multi-sensor diagnostics strength.
    """
    now_s = 250.0
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: now_s)
    engine = LiveDiagnosticsEngine()

    def fake_apply(
        self: LiveDiagnosticsEngine,
        tracker: _TrackerLevelState,
        *,
        vibration_strength_db: float,
        sensor_count: int,
        fallback_db: float | None = None,
    ) -> str | None:
        previous = tracker.current_bucket_key
        tracker.current_bucket_key = "l2"
        tracker.last_strength_db = float(vibration_strength_db)
        return previous

    monkeypatch.setattr(
        engine,
        "_apply_severity_to_tracker",
        MethodType(fake_apply, engine),
    )

    sensor_events = [
        _RecentEvent(
            ts_ms=250000,
            sensor_id="s1",
            sensor_label="front-left",
            sensor_location="front-left",
            peak_hz=31.0,
            peak_amp=0.1,
            vibration_strength_db=10.0,
            class_key="wheel",
        ),
        _RecentEvent(
            ts_ms=250000,
            sensor_id="s2",
            sensor_label="front-right",
            sensor_location="front-right",
            peak_hz=31.2,
            peak_amp=0.2,
            vibration_strength_db=20.0,
            class_key="wheel",
        ),
    ]
    monkeypatch.setattr(engine, "_detect_sensor_events", lambda **_: sensor_events)

    engine.update(
        speed_mps=20.0,
        clients=[{"id": "s1", "name": "front-left"}, {"id": "s2", "name": "front-right"}],
        spectra={"freq": [1.0], "clients": {}},
        settings={},
    )

    assert engine._combined_trackers
    combined_tracker = next(iter(engine._combined_trackers.values()))
    expected_db = 20.0 * math.log10((10 ** (10.0 / 20.0) + 10 ** (20.0 / 20.0)) / 2.0)
    assert combined_tracker.last_strength_db == pytest.approx(expected_db, abs=1e-6)


def test_levels_by_location_includes_confidence_boost_for_agreement(monkeypatch) -> None:
    now_s = 300.0
    monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: now_s)
    engine = LiveDiagnosticsEngine()

    def fake_apply(
        self: LiveDiagnosticsEngine,
        tracker: _TrackerLevelState,
        *,
        vibration_strength_db: float,
        sensor_count: int,
        fallback_db: float | None = None,
    ) -> str | None:
        previous = tracker.current_bucket_key
        tracker.current_bucket_key = "l2"
        tracker.last_strength_db = float(vibration_strength_db)
        return previous

    monkeypatch.setattr(
        engine,
        "_apply_severity_to_tracker",
        MethodType(fake_apply, engine),
    )

    sensor_events = [
        _RecentEvent(
            ts_ms=300000,
            sensor_id="s1",
            sensor_label="front-left-a",
            sensor_location="front-left-wheel",
            peak_hz=40.0,
            peak_amp=0.12,
            vibration_strength_db=21.0,
            class_key="wheel",
        ),
        _RecentEvent(
            ts_ms=300000,
            sensor_id="s2",
            sensor_label="front-left-b",
            sensor_location="front-left-wheel",
            peak_hz=40.3,
            peak_amp=0.11,
            vibration_strength_db=20.0,
            class_key="wheel",
        ),
    ]
    monkeypatch.setattr(engine, "_detect_sensor_events", lambda **_: sensor_events)

    snap = engine.update(
        speed_mps=20.0,
        clients=[
            {"id": "s1", "name": "front-left-a", "location": "front-left-wheel"},
            {"id": "s2", "name": "front-left-b", "location": "front-left-wheel"},
        ],
        spectra={"freq": [1.0], "clients": {}},
        settings={},
    )

    by_location = snap["levels"]["by_location"]
    assert "front-left-wheel" in by_location
    row = by_location["front-left-wheel"]
    assert row["bucket_key"] == "l2"
    assert row["agreement_count"] == 2
    assert row["sensor_count"] == 2
    assert row["confidence"] == pytest.approx(2.0)
