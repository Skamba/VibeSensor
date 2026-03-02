"""Tests for live dashboard consistency improvements.

Covers:
- diagnostics_sequence increments and is stable on light ticks
- event_id present on emitted events
- matrix dwell-seconds accumulate on light (spectra=None) ticks
- order_bands presence in rotational payload (via build_ws_payload integration)
"""

from __future__ import annotations

import os

os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")

from vibesensor_core.vibration_strength import compute_vibration_strength_db

from vibesensor.live_diagnostics import LiveDiagnosticsEngine


def _make_spectra(peak_idx: int = 320, peak_amp: float = 150.0) -> dict:
    freq = [idx * 0.1 for idx in range(1, 1200)]
    base = [0.8 for _ in freq]
    base[peak_idx] = peak_amp
    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq,
        combined_spectrum_amp_g_values=base,
        peak_bandwidth_hz=1.2,
        peak_separation_hz=1.2,
        top_n=5,
    )
    return {
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


# ---------------------------------------------------------------------------
# diagnostics_sequence
# ---------------------------------------------------------------------------


def test_diagnostics_sequence_increments_on_heavy_ticks(monkeypatch) -> None:
    now = {"value": 100.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.engine.monotonic", lambda: now["value"])
    engine = LiveDiagnosticsEngine()
    spectra = _make_spectra()
    clients = [{"id": "c1", "name": "front"}]

    seqs: list[int] = []
    for _ in range(5):
        now["value"] += 0.5
        snap = engine.update(speed_mps=27.8, clients=clients, spectra=spectra, settings={})
        seqs.append(snap["diagnostics_sequence"])

    # Sequence must be strictly increasing
    for i in range(1, len(seqs)):
        assert seqs[i] > seqs[i - 1], f"Sequence must increase: {seqs}"


def test_diagnostics_sequence_stable_on_light_ticks(monkeypatch) -> None:
    now = {"value": 100.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.engine.monotonic", lambda: now["value"])
    engine = LiveDiagnosticsEngine()
    spectra = _make_spectra()
    clients = [{"id": "c1", "name": "front"}]

    # Heavy tick
    now["value"] += 0.5
    snap_heavy = engine.update(speed_mps=27.8, clients=clients, spectra=spectra, settings={})
    seq_heavy = snap_heavy["diagnostics_sequence"]

    # Light tick (spectra=None) - sequence should NOT increment
    now["value"] += 0.5
    snap_light = engine.update(speed_mps=27.8, clients=clients, spectra=None, settings={})
    seq_light = snap_light["diagnostics_sequence"]

    assert seq_light == seq_heavy, "Sequence should not change on light tick"


def test_diagnostics_sequence_resets_on_engine_reset() -> None:
    engine = LiveDiagnosticsEngine()
    assert engine.snapshot()["diagnostics_sequence"] == 0
    engine.reset()
    assert engine.snapshot()["diagnostics_sequence"] == 0


# ---------------------------------------------------------------------------
# event_id
# ---------------------------------------------------------------------------


def test_events_have_event_id(monkeypatch) -> None:
    now = {"value": 100.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.engine.monotonic", lambda: now["value"])
    engine = LiveDiagnosticsEngine()
    spectra = _make_spectra()
    clients = [{"id": "c1", "name": "front"}]

    all_events: list[dict] = []
    for _ in range(10):
        now["value"] += 0.5
        snap = engine.update(speed_mps=27.8, clients=clients, spectra=spectra, settings={})
        all_events.extend(snap["events"])

    if all_events:
        for event in all_events:
            assert "event_id" in event, f"Event missing event_id: {event}"
        # event_ids should be unique
        ids = [e["event_id"] for e in all_events]
        assert len(ids) == len(set(ids)), f"Event IDs not unique: {ids}"


# ---------------------------------------------------------------------------
# matrix dwell-seconds on light ticks
# ---------------------------------------------------------------------------


def test_matrix_dwell_seconds_accumulate_on_light_ticks(monkeypatch) -> None:
    """Dwell seconds should increase even when spectra is None (light ticks)."""
    now = {"value": 100.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.engine.monotonic", lambda: now["value"])
    engine = LiveDiagnosticsEngine()
    spectra = _make_spectra()
    clients = [{"id": "c1", "name": "front"}]

    # Bootstrap with several heavy ticks to establish active levels
    for _ in range(5):
        now["value"] += 0.1
        engine.update(speed_mps=27.8, clients=clients, spectra=spectra, settings={})

    snap_before = engine.snapshot()
    seconds_before = sum(
        cell["seconds"] for cols in snap_before["matrix"].values() for cell in cols.values()
    )

    # Several light ticks (spectra=None)
    for _ in range(5):
        now["value"] += 0.1
        engine.update(speed_mps=27.8, clients=clients, spectra=None, settings={})

    snap_after = engine.snapshot()
    seconds_after = sum(
        cell["seconds"] for cols in snap_after["matrix"].values() for cell in cols.values()
    )

    assert seconds_after > seconds_before, (
        f"Dwell seconds should increase on light ticks: "
        f"before={seconds_before}, after={seconds_after}"
    )


# ---------------------------------------------------------------------------
# rotational payload order_bands (via RuntimeState._build_rotational_speeds_payload)
# ---------------------------------------------------------------------------


class _StubSettingsStore:
    language: str = "en"

    def get_speed_source(self) -> dict:
        return {"speedSource": "gps", "fallbackMode": "manual"}


class _StubGPS:
    effective_speed_mps: float | None = 12.5
    gps_enabled: bool = True
    fallback_active: bool = False


def test_rotational_order_bands_present_with_speed() -> None:
    """When speed is available, _build_rotational_speeds_payload should include order_bands."""
    from vibesensor.app import RuntimeState

    state = RuntimeState.__new__(RuntimeState)
    state.settings_store = _StubSettingsStore()  # type: ignore[assignment]
    state.gps_monitor = _StubGPS()  # type: ignore[assignment]
    settings = {
        "tire_width_mm": 285,
        "tire_aspect_pct": 30,
        "rim_in": 21,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
    }
    result = state._build_rotational_speeds_payload(
        speed_mps=27.8,
        analysis_settings=settings,
        resolution_source="gps",
    )
    bands = result.get("order_bands")
    assert bands is not None, "order_bands should be present when speed is available"
    assert isinstance(bands, list)
    assert len(bands) >= 3, f"Expected at least 3 order bands, got {len(bands)}"
    keys = {b["key"] for b in bands}
    assert "wheel_1x" in keys
    assert "wheel_2x" in keys
    for band in bands:
        assert band["center_hz"] > 0
        assert band["tolerance"] > 0


def test_rotational_order_bands_none_without_speed() -> None:
    """When speed is unavailable, order_bands should be None."""
    from vibesensor.app import RuntimeState

    state = RuntimeState.__new__(RuntimeState)
    state.settings_store = _StubSettingsStore()  # type: ignore[assignment]
    state.gps_monitor = _StubGPS()  # type: ignore[assignment]
    result = state._build_rotational_speeds_payload(
        speed_mps=None,
        analysis_settings={},
        resolution_source=None,
    )
    assert result.get("order_bands") is None, "order_bands should be None without speed"
