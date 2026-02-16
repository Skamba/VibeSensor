from __future__ import annotations

from vibesensor.analysis.strength_metrics import compute_strength_metrics
from vibesensor.diagnostics_shared import severity_from_peak
from vibesensor.live_diagnostics import LiveDiagnosticsEngine
from vibesensor.strength_bands import DECAY_TICKS, HYSTERESIS_DB, band_by_key


def test_severity_holds_for_small_hysteresis_dip_then_decays() -> None:
    state = None
    out = None
    for _ in range(3):
        out = severity_from_peak(strength_db=23.0, band_rms=0.02, sensor_count=1, prior_state=state)
        state = dict((out or {}).get("state") or {})
    assert out is not None
    assert out["key"] == "l3"

    l3 = band_by_key("l3")
    assert l3 is not None
    slight_dip = float(l3["min_db"]) - (HYSTERESIS_DB / 2)
    out = severity_from_peak(strength_db=slight_dip, band_rms=0.02, sensor_count=1, prior_state=state)
    state = dict((out or {}).get("state") or state or {})
    assert out is not None
    assert out["key"] == "l3"

    for _ in range(DECAY_TICKS):
        out = severity_from_peak(strength_db=-120.0, band_rms=0.0, sensor_count=1, prior_state=state)
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
    strength_metrics = compute_strength_metrics(
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
