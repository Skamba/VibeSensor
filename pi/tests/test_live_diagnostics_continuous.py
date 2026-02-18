from __future__ import annotations

from vibesensor.analysis.vibration_strength import compute_vibration_strength_db
from vibesensor.constants import SILENCE_DB
from vibesensor.diagnostics_shared import severity_from_peak
from vibesensor.live_diagnostics import LiveDiagnosticsEngine
from vibesensor.strength_bands import DECAY_TICKS, HYSTERESIS_DB, band_by_key


def test_severity_holds_for_small_hysteresis_dip_then_decays() -> None:
    state = None
    out = None
    for _ in range(3):
        out = severity_from_peak(vibration_strength_db=23.0, sensor_count=1, prior_state=state)
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


def test_live_matrix_seconds_accumulate_during_throttled_emission(monkeypatch) -> None:
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
    assert max_seconds >= 8.0

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
    """Matrix should not be lost on light ticks."""
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

    # Several heavy ticks to accumulate matrix
    for _ in range(5):
        current_s["value"] += 1.0
        engine.update(
            speed_mps=27.8,
            clients=[{"id": "c1", "name": "front"}],
            spectra=spectra,
            settings={},
        )

    snap_before = engine.snapshot()
    matrix_before = snap_before["matrix"]

    # Light tick should preserve matrix
    current_s["value"] += 0.1
    snap_after = engine.update(
        speed_mps=27.8,
        clients=[{"id": "c1", "name": "front"}],
        spectra=None,
        settings={},
    )
    assert snap_after["matrix"] == matrix_before, "Matrix should be preserved on light tick"
