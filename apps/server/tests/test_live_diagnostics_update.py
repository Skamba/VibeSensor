"""Integration tests for LiveDiagnosticsEngine.update() — the main entry point.

These tests exercise the full update() cycle with realistic spectra payloads
and validate the output contract (matrix, events, levels, snapshot) across
multiple ticks.
"""

from __future__ import annotations

from vibesensor_core.vibration_strength import compute_vibration_strength_db

from vibesensor.live_diagnostics import LiveDiagnosticsEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spectra(
    client_ids: list[str],
    *,
    peak_idx: int = 320,
    peak_amp: float = 150.0,
    background: float = 0.8,
    num_bins: int = 1200,
) -> dict:
    """Build a minimal but realistic spectra payload for update()."""
    freq = [idx * 0.1 for idx in range(1, num_bins)]
    base = [background] * len(freq)
    base[peak_idx] = peak_amp

    strength_metrics = compute_vibration_strength_db(
        freq_hz=freq,
        combined_spectrum_amp_g_values=base,
        peak_bandwidth_hz=1.2,
        peak_separation_hz=1.2,
        top_n=5,
    )

    clients: dict[str, dict] = {}
    for cid in client_ids:
        clients[cid] = {
            "freq": freq,
            "x": list(base),
            "y": list(base),
            "z": list(base),
            "combined_spectrum_amp_g": list(base),
            "strength_metrics": strength_metrics,
        }
    return {"freq": freq, "clients": clients}


def _make_clients(
    ids_names: list[tuple[str, str]],
    *,
    locations: dict[str, str] | None = None,
) -> list[dict]:
    """Build a minimal clients list for update()."""
    loc = locations or {}
    return [{"id": cid, "name": name, "location": loc.get(cid, "")} for cid, name in ids_names]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpdateSnapshotContract:
    """Verify that update() returns the expected snapshot shape."""

    def test_snapshot_keys_present(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        spectra = _make_spectra(["c1"])
        clients = _make_clients([("c1", "front")])

        snap = engine.update(
            speed_mps=20.0,
            clients=clients,
            spectra=spectra,
            settings={},
        )

        required_keys = {
            "diagnostics_sequence",
            "matrix",
            "events",
            "strength_bands",
            "levels",
            "findings",
            "top_finding",
            "driving_phase",
            "error",
        }
        assert required_keys.issubset(snap.keys()), f"Missing: {required_keys - snap.keys()}"

    def test_matrix_has_expected_sources_and_severities(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        snap = engine.update(
            speed_mps=None,
            clients=[],
            spectra=None,
            settings={},
        )

        expected_sources = {"engine", "driveshaft", "wheel", "other"}
        expected_severities = {"l5", "l4", "l3", "l2", "l1"}
        assert set(snap["matrix"].keys()) == expected_sources
        for source_cells in snap["matrix"].values():
            assert set(source_cells.keys()) == expected_severities
            for cell in source_cells.values():
                assert "count" in cell
                assert "seconds" in cell
                assert "contributors" in cell

    def test_levels_has_expected_sub_dicts(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        snap = engine.update(
            speed_mps=20.0,
            clients=[],
            spectra=None,
            settings={},
        )

        assert "levels" in snap
        assert "by_source" in snap["levels"]
        assert "by_sensor" in snap["levels"]
        assert "by_location" in snap["levels"]


class TestSingleSensorEventEmission:
    """Verify that a single sensor with a strong peak produces events after enough ticks."""

    def test_events_emitted_after_persistence(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        spectra = _make_spectra(["c1"], peak_amp=150.0)
        clients = _make_clients([("c1", "front")])

        # Several ticks to pass persistence threshold
        all_events: list[dict] = []
        for _ in range(10):
            t["now"] += 1.0
            snap = engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=spectra,
                settings={},
            )
            all_events.extend(snap.get("events", []))

        assert len(all_events) > 0, "Expected at least one event after persistence ticks"
        event = all_events[0]
        assert "event_id" in event
        assert "kind" in event
        assert event["kind"] == "single"
        assert "class_key" in event
        assert "peak_hz" in event
        assert "severity_key" in event
        assert "vibration_strength_db" in event

    def test_sequence_increments_per_tick(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        spectra = _make_spectra(["c1"])
        clients = _make_clients([("c1", "front")])

        seqs = []
        for _ in range(5):
            t["now"] += 0.5
            snap = engine.update(
                speed_mps=20.0,
                clients=clients,
                spectra=spectra,
                settings={},
            )
            seqs.append(snap["diagnostics_sequence"])

        assert seqs == list(range(1, 6))


class TestTrackerDecay:
    """Verify that trackers decay to silence when spectra stop carrying peaks."""

    def test_tracker_decays_after_peak_disappears(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        strong_spectra = _make_spectra(["c1"], peak_amp=150.0)
        weak_spectra = _make_spectra(["c1"], peak_amp=0.01, background=0.8)
        clients = _make_clients([("c1", "front")])

        # Build up tracker state with strong peaks
        for _ in range(8):
            t["now"] += 1.0
            engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=strong_spectra,
                settings={},
            )

        # Now send weak spectra for many ticks — tracker should eventually decay
        for _ in range(30):
            t["now"] += 1.0
            snap = engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=weak_spectra,
                settings={},
            )

        # After enough silence ticks, the by_source levels should be empty or nil
        by_source = snap["levels"]["by_source"]
        # Either empty or all have decayed to None bucket
        for source_state in by_source.values():
            if source_state.get("bucket_key") is not None:
                # If still present, strength should be very low
                assert source_state.get("strength_db", 0) < 10.0


class TestLightTickBehavior:
    """Verify correct behavior when spectra=None (light ticks)."""

    def test_light_tick_accumulates_dwell_seconds(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        spectra = _make_spectra(["c1"], peak_amp=150.0)
        clients = _make_clients([("c1", "front")])

        # Build up state with heavy ticks
        for _ in range(6):
            t["now"] += 1.0
            engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=spectra,
                settings={},
            )

        snap_before = engine.snapshot()
        total_sec_before = sum(
            cell["seconds"] for cols in snap_before["matrix"].values() for cell in cols.values()
        )

        # Light tick with dt=2 seconds — should still accumulate dwell
        t["now"] += 2.0
        snap_after = engine.update(
            speed_mps=27.8,
            clients=clients,
            spectra=None,
            settings={},
        )
        total_sec_after = sum(
            cell["seconds"] for cols in snap_after["matrix"].values() for cell in cols.values()
        )
        # The total may grow if any source has an active bucket
        assert total_sec_after >= total_sec_before

    def test_light_tick_does_not_clear_matrix_counts(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        spectra = _make_spectra(["c1"], peak_amp=150.0)
        clients = _make_clients([("c1", "front")])

        # Build up state
        for _ in range(8):
            t["now"] += 1.0
            engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=spectra,
                settings={},
            )

        total_counts_before = sum(
            cell["count"] for cols in engine.snapshot()["matrix"].values() for cell in cols.values()
        )

        # Light tick
        t["now"] += 0.1
        snap = engine.update(
            speed_mps=27.8,
            clients=clients,
            spectra=None,
            settings={},
        )
        total_counts_after = sum(
            cell["count"] for cols in snap["matrix"].values() for cell in cols.values()
        )
        assert total_counts_after >= total_counts_before


class TestMalformedSpectra:
    """Verify that malformed spectra payloads are handled gracefully."""

    def test_missing_clients_key_returns_snapshot_without_crash(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        # spectra without 'clients' key — should not crash
        snap = engine.update(
            speed_mps=20.0,
            clients=[{"id": "c1", "name": "front"}],
            spectra={"freq": [1.0]},
            settings={},
        )
        assert "matrix" in snap
        assert snap["error"] is None

    def test_clients_not_dict_returns_snapshot_without_crash(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        snap = engine.update(
            speed_mps=20.0,
            clients=[{"id": "c1", "name": "front"}],
            spectra={"freq": [1.0], "clients": "not_a_dict"},
            settings={},
        )
        assert "matrix" in snap
        assert snap["error"] is None

    def test_missing_strength_metrics_returns_snapshot_without_crash(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        snap = engine.update(
            speed_mps=20.0,
            clients=[{"id": "c1", "name": "front"}],
            spectra={
                "freq": [1.0],
                "clients": {"c1": {"freq": [1.0], "x": [0.1], "y": [0.1], "z": [0.1]}},
            },
            settings={},
        )
        assert "matrix" in snap
        assert snap["error"] is None


class TestMultiSensorGrouping:
    """Verify that multiple sensors seeing the same frequency form combined groups."""

    def test_combined_events_emitted_for_two_sensors(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        # Same peak for both sensors
        spectra = _make_spectra(["s1", "s2"], peak_amp=150.0)
        clients = _make_clients([("s1", "front-left"), ("s2", "front-right")])

        all_events: list[dict] = []
        for _ in range(12):
            t["now"] += 1.0
            snap = engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=spectra,
                settings={},
            )
            all_events.extend(snap.get("events", []))

        multi_events = [e for e in all_events if e.get("kind") == "multi"]
        assert len(multi_events) > 0, "Expected at least one 'multi' event from two sensors"
        assert multi_events[0]["sensor_count"] >= 2


class TestDrivingPhase:
    """Verify driving phase classification via update()."""

    def test_phase_is_speed_unknown_without_speed(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        snap = engine.update(
            speed_mps=None,
            clients=[],
            spectra=None,
            settings={},
        )
        assert snap["driving_phase"] == "speed_unknown"

    def test_phase_reflects_speed_at_steady_speed(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        for _ in range(6):
            t["now"] += 1.0
            snap = engine.update(
                speed_mps=25.0,
                clients=[],
                spectra=None,
                settings={},
            )
        # After steady speed, phase should not be speed_unknown
        assert snap["driving_phase"] != "speed_unknown"


class TestResetClearsState:
    """Verify that reset() clears all accumulated state."""

    def test_reset_zeroes_matrix_and_events(self, monkeypatch) -> None:
        t = {"now": 10.0}
        monkeypatch.setattr("vibesensor.live_diagnostics.monotonic", lambda: t["now"])

        engine = LiveDiagnosticsEngine()
        spectra = _make_spectra(["c1"], peak_amp=150.0)
        clients = _make_clients([("c1", "front")])

        for _ in range(8):
            t["now"] += 1.0
            engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=spectra,
                settings={},
            )

        engine.reset()
        snap = engine.snapshot()

        total_counts = sum(
            cell["count"] for cols in snap["matrix"].values() for cell in cols.values()
        )
        assert total_counts == 0
        assert snap["events"] == []
        assert snap["diagnostics_sequence"] == 0
