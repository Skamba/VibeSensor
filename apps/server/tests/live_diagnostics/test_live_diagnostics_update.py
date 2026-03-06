"""Integration tests for LiveDiagnosticsEngine.update() — the main entry point.

These tests exercise the full update() cycle with realistic spectra payloads
and validate the output contract (matrix, events, levels, snapshot) across
multiple ticks.
"""

from __future__ import annotations

import pytest
from vibesensor_core.vibration_strength import compute_vibration_strength_db

from vibesensor.live_diagnostics import LiveDiagnosticsEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CLIENTS = [("c1", "front")]


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


def _matrix_total(snap: dict, field: str) -> int | float:
    """Sum a numeric *field* across all matrix cells."""
    return sum(cell[field] for cols in snap["matrix"].values() for cell in cols.values())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def diag_env(monkeypatch):
    """LiveDiagnosticsEngine with a controllable monotonic clock.

    Attributes:
        engine: the engine instance
        t: mutable time dict – advance via ``t["now"] += dt``
        tick(n, ...): run *n* update() calls, advancing *dt* each time
    """
    t = {"now": 10.0}
    monkeypatch.setattr("vibesensor.live_diagnostics.engine.monotonic", lambda: t["now"])
    engine = LiveDiagnosticsEngine()

    def tick(
        n: int,
        *,
        dt: float = 1.0,
        speed_mps: float = 27.8,
        clients=None,
        spectra=None,
        settings=None,
    ):
        """Run *n* update ticks, return the last snapshot."""
        snap = None
        for _ in range(n):
            t["now"] += dt
            snap = engine.update(
                speed_mps=speed_mps,
                clients=clients if clients is not None else [],
                spectra=spectra,
                settings=settings or {},
            )
        return snap

    class _Env:
        pass

    env = _Env()
    env.t = t  # type: ignore[attr-defined]
    env.engine = engine  # type: ignore[attr-defined]
    env.tick = tick  # type: ignore[attr-defined]
    return env


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpdateSnapshotContract:
    """Verify that update() returns the expected snapshot shape."""

    def test_snapshot_keys_present(self, diag_env) -> None:
        spectra = _make_spectra(["c1"])
        clients = _make_clients(_DEFAULT_CLIENTS)

        snap = diag_env.engine.update(
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

    def test_matrix_has_expected_sources_and_severities(self, diag_env) -> None:
        snap = diag_env.engine.update(
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

    def test_levels_has_expected_sub_dicts(self, diag_env) -> None:
        snap = diag_env.engine.update(
            speed_mps=20.0,
            clients=[],
            spectra=None,
            settings={},
        )

        assert "levels" in snap
        for key in ("by_source", "by_sensor", "by_location"):
            assert key in snap["levels"]


class TestSingleSensorEventEmission:
    """Verify that a single sensor with a strong peak produces events after enough ticks."""

    def test_events_emitted_after_persistence(self, diag_env) -> None:
        spectra = _make_spectra(["c1"], peak_amp=150.0)
        clients = _make_clients(_DEFAULT_CLIENTS)

        all_events: list[dict] = []
        for _ in range(10):
            diag_env.t["now"] += 1.0
            snap = diag_env.engine.update(
                speed_mps=27.8,
                clients=clients,
                spectra=spectra,
                settings={},
            )
            all_events.extend(snap.get("events", []))

        assert len(all_events) > 0, "Expected at least one event after persistence ticks"
        event = all_events[0]
        for key in (
            "event_id",
            "kind",
            "class_key",
            "peak_hz",
            "severity_key",
            "vibration_strength_db",
        ):
            assert key in event
        assert event["kind"] == "single"

    def test_sequence_increments_per_tick(self, diag_env) -> None:
        spectra = _make_spectra(["c1"])
        clients = _make_clients(_DEFAULT_CLIENTS)

        seqs = []
        for _ in range(5):
            diag_env.t["now"] += 0.5
            snap = diag_env.engine.update(
                speed_mps=20.0,
                clients=clients,
                spectra=spectra,
                settings={},
            )
            seqs.append(snap["diagnostics_sequence"])

        assert seqs == list(range(1, 6))


class TestTrackerDecay:
    """Verify that trackers decay to silence when spectra stop carrying peaks."""

    def test_tracker_decays_after_peak_disappears(self, diag_env) -> None:
        strong_spectra = _make_spectra(["c1"], peak_amp=150.0)
        weak_spectra = _make_spectra(["c1"], peak_amp=0.01, background=0.8)
        clients = _make_clients(_DEFAULT_CLIENTS)

        # Build up tracker state with strong peaks
        diag_env.tick(8, clients=clients, spectra=strong_spectra)

        # Now send weak spectra for many ticks — tracker should eventually decay
        snap = diag_env.tick(30, clients=clients, spectra=weak_spectra)

        # After enough silence ticks, the by_source levels should be empty or nil
        by_source = snap["levels"]["by_source"]
        for source_state in by_source.values():
            if source_state.get("bucket_key") is not None:
                # If still present, strength should be very low
                assert source_state.get("strength_db", 0) < 10.0


class TestLightTickBehavior:
    """Verify correct behavior when spectra=None (light ticks)."""

    def _build_state(self, diag_env, n=6):
        """Feed *n* heavy ticks and return the clients list."""
        spectra = _make_spectra(["c1"], peak_amp=150.0)
        clients = _make_clients(_DEFAULT_CLIENTS)
        diag_env.tick(n, clients=clients, spectra=spectra)
        return clients

    def test_light_tick_accumulates_dwell_seconds(self, diag_env) -> None:
        clients = self._build_state(diag_env)
        total_before = _matrix_total(diag_env.engine.snapshot(), "seconds")

        # Light tick with dt=2 seconds — should still accumulate dwell
        diag_env.t["now"] += 2.0
        snap_after = diag_env.engine.update(
            speed_mps=27.8,
            clients=clients,
            spectra=None,
            settings={},
        )
        assert _matrix_total(snap_after, "seconds") >= total_before

    def test_light_tick_does_not_clear_matrix_counts(self, diag_env) -> None:
        clients = self._build_state(diag_env, n=8)
        total_before = _matrix_total(diag_env.engine.snapshot(), "count")

        # Light tick
        diag_env.t["now"] += 0.1
        snap = diag_env.engine.update(
            speed_mps=27.8,
            clients=clients,
            spectra=None,
            settings={},
        )
        assert _matrix_total(snap, "count") >= total_before


class TestMalformedSpectra:
    """Verify that malformed spectra payloads are handled gracefully."""

    @pytest.mark.parametrize(
        "spectra_payload",
        [
            pytest.param({"freq": [1.0]}, id="missing-clients-key"),
            pytest.param({"freq": [1.0], "clients": "not_a_dict"}, id="clients-not-dict"),
            pytest.param(
                {
                    "freq": [1.0],
                    "clients": {"c1": {"freq": [1.0], "x": [0.1], "y": [0.1], "z": [0.1]}},
                },
                id="missing-strength-metrics",
            ),
        ],
    )
    def test_malformed_spectra_returns_snapshot_without_crash(
        self,
        diag_env,
        spectra_payload,
    ) -> None:
        snap = diag_env.engine.update(
            speed_mps=20.0,
            clients=[{"id": "c1", "name": "front"}],
            spectra=spectra_payload,
            settings={},
        )
        assert "matrix" in snap
        assert snap["error"] is None


class TestMultiSensorGrouping:
    """Verify that multiple sensors seeing the same frequency form combined groups."""

    def test_combined_events_emitted_for_two_sensors(self, diag_env) -> None:
        spectra = _make_spectra(["s1", "s2"], peak_amp=150.0)
        clients = _make_clients([("s1", "front-left"), ("s2", "front-right")])

        all_events: list[dict] = []
        for _ in range(12):
            diag_env.t["now"] += 1.0
            snap = diag_env.engine.update(
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

    def test_phase_is_speed_unknown_without_speed(self, diag_env) -> None:
        snap = diag_env.engine.update(
            speed_mps=None,
            clients=[],
            spectra=None,
            settings={},
        )
        assert snap["driving_phase"] == "speed_unknown"

    def test_phase_reflects_speed_at_steady_speed(self, diag_env) -> None:
        snap = diag_env.tick(6, speed_mps=25.0)
        # After steady speed, phase should not be speed_unknown
        assert snap["driving_phase"] != "speed_unknown"


class TestResetClearsState:
    """Verify that reset() clears all accumulated state."""

    def test_reset_zeroes_matrix_and_events(self, diag_env) -> None:
        spectra = _make_spectra(["c1"], peak_amp=150.0)
        clients = _make_clients(_DEFAULT_CLIENTS)

        diag_env.tick(8, clients=clients, spectra=spectra)

        diag_env.engine.reset()
        snap = diag_env.engine.snapshot()

        assert _matrix_total(snap, "count") == 0
        assert snap["events"] == []
        assert snap["diagnostics_sequence"] == 0
