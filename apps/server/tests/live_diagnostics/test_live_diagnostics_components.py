"""Unit tests for the extracted live_diagnostics submodules.

These tests verify that each submodule is independently testable after the
god-object refactor of LiveDiagnosticsEngine → live_diagnostics/ package.
"""

from __future__ import annotations

import pytest

from vibesensor.constants import SILENCE_DB

# ---------------------------------------------------------------------------
# _types: _combine_amplitude_strength_db
# ---------------------------------------------------------------------------


class TestCombineAmplitudeStrengthDb:
    """Tests for the pure _combine_amplitude_strength_db helper."""

    def test_empty_list_returns_silence(self) -> None:
        from vibesensor.live_diagnostics._types import _combine_amplitude_strength_db

        assert _combine_amplitude_strength_db([]) == SILENCE_DB

    def test_single_value_roundtrips(self) -> None:
        from vibesensor.live_diagnostics._types import _combine_amplitude_strength_db

        result = _combine_amplitude_strength_db([15.0])
        assert result == pytest.approx(15.0, abs=0.5)

    def test_mean_of_two_values_is_in_linear_domain(self) -> None:
        from vibesensor.live_diagnostics._types import _combine_amplitude_strength_db

        result = _combine_amplitude_strength_db([10.0, 20.0])
        naive_mean = (10.0 + 20.0) / 2
        assert result != pytest.approx(naive_mean, abs=0.1), "should NOT be arithmetic mean"

    def test_nan_values_are_skipped(self) -> None:
        from vibesensor.live_diagnostics._types import _combine_amplitude_strength_db

        clean = _combine_amplitude_strength_db([10.0, 20.0])
        with_nan = _combine_amplitude_strength_db([10.0, float("nan"), 20.0])
        assert with_nan == pytest.approx(clean, abs=1e-6)

    def test_all_nan_returns_silence(self) -> None:
        from vibesensor.live_diagnostics._types import _combine_amplitude_strength_db

        assert _combine_amplitude_strength_db([float("nan")]) == SILENCE_DB


# ---------------------------------------------------------------------------
# severity_matrix: SeverityMatrix
# ---------------------------------------------------------------------------


class TestSeverityMatrix:
    """Tests for the extracted SeverityMatrix component."""

    def test_new_matrix_has_all_sources_and_severities(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        data = m.data
        for source in ("engine", "driveshaft", "wheel", "other"):
            assert source in data
            for severity in ("l5", "l4", "l3", "l2", "l1"):
                assert severity in data[source]
                cell = data[source][severity]
                assert cell["count"] == 0
                assert cell["seconds"] == 0.0

    def test_record_count_increments(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        m.record_count(1000, "wheel", "l3", "sensor-1")
        m.record_count(2000, "wheel", "l3", "sensor-1")
        m.rebuild(3000)
        assert m.data["wheel"]["l3"]["count"] == 2

    def test_record_many_fans_out_to_sources(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        m.record_many(1000, ("engine", "wheel"), "l2", "s1")
        m.rebuild(2000)
        assert m.data["engine"]["l2"]["count"] == 1
        assert m.data["wheel"]["l2"]["count"] == 1
        assert m.data["driveshaft"]["l2"]["count"] == 0

    def test_accumulate_seconds_adds_dwell_time(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        levels = {"engine": {"bucket_key": "l2"}}
        m.accumulate_seconds(1000, 0.5, levels)
        m.rebuild(2000)
        assert m.data["engine"]["l2"]["seconds"] == pytest.approx(0.5)

    def test_rebuild_prunes_old_events(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        # Record at time 0
        m.record_count(0, "wheel", "l1", "s1")
        m.rebuild(0)
        assert m.data["wheel"]["l1"]["count"] == 1
        # Rebuild at time far in the future (past 5-minute window)
        m.rebuild(10 * 60 * 1000)
        assert m.data["wheel"]["l1"]["count"] == 0

    def test_copy_is_deep(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        m.record_count(1000, "wheel", "l3", "s1")
        m.rebuild(2000)
        copy = m.copy()
        copy["wheel"]["l3"]["count"] = 999
        assert m.data["wheel"]["l3"]["count"] != 999

    def test_reset_clears_all_state(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        m.record_count(1000, "wheel", "l3", "s1")
        m.rebuild(2000)
        m.reset()
        for source in m.data:
            for severity in m.data[source]:
                assert m.data[source][severity]["count"] == 0

    def test_invalid_source_ignored(self) -> None:
        from vibesensor.live_diagnostics.severity_matrix import SeverityMatrix

        m = SeverityMatrix()
        m.record_count(1000, "nonexistent", "l3", "s1")
        m.rebuild(2000)
        # Should not crash; all valid sources should still be zero
        for source in m.data:
            for severity in m.data[source]:
                assert m.data[source][severity]["count"] == 0


# ---------------------------------------------------------------------------
# tracker: severity tracking functions
# ---------------------------------------------------------------------------


class TestTrackerFunctions:
    """Tests for the extracted severity tracking functions."""

    def test_should_emit_on_new_bucket(self) -> None:
        from vibesensor.live_diagnostics._types import _TrackerLevelState
        from vibesensor.live_diagnostics.tracker import should_emit_event

        tracker = _TrackerLevelState()
        assert should_emit_event(tracker, None, "l1", now_ms=1000, heartbeat_ms=3000) is True

    def test_should_not_emit_on_none_bucket(self) -> None:
        from vibesensor.live_diagnostics._types import _TrackerLevelState
        from vibesensor.live_diagnostics.tracker import should_emit_event

        tracker = _TrackerLevelState()
        assert should_emit_event(tracker, None, None, now_ms=1000, heartbeat_ms=3000) is False

    def test_should_emit_on_escalation(self) -> None:
        from vibesensor.live_diagnostics._types import _TrackerLevelState
        from vibesensor.live_diagnostics.tracker import should_emit_event

        tracker = _TrackerLevelState()
        assert should_emit_event(tracker, "l1", "l3", now_ms=1000, heartbeat_ms=3000) is True

    def test_should_emit_heartbeat_after_interval(self) -> None:
        from vibesensor.live_diagnostics._types import _TrackerLevelState
        from vibesensor.live_diagnostics.tracker import should_emit_event

        tracker = _TrackerLevelState(last_emitted_ms=0)
        assert should_emit_event(tracker, "l2", "l2", now_ms=4000, heartbeat_ms=3000) is True

    def test_no_heartbeat_within_interval(self) -> None:
        from vibesensor.live_diagnostics._types import _TrackerLevelState
        from vibesensor.live_diagnostics.tracker import should_emit_event

        tracker = _TrackerLevelState(last_emitted_ms=1000)
        assert should_emit_event(tracker, "l2", "l2", now_ms=2000, heartbeat_ms=3000) is False

    def test_matrix_transition_new(self) -> None:
        from vibesensor.live_diagnostics.tracker import matrix_transition_bucket

        assert matrix_transition_bucket(None, "l1") == "l1"

    def test_matrix_transition_escalation(self) -> None:
        from vibesensor.live_diagnostics.tracker import matrix_transition_bucket

        assert matrix_transition_bucket("l1", "l3") == "l3"

    def test_matrix_transition_same_returns_none(self) -> None:
        from vibesensor.live_diagnostics.tracker import matrix_transition_bucket

        assert matrix_transition_bucket("l2", "l2") is None

    def test_matrix_transition_downgrade_returns_none(self) -> None:
        from vibesensor.live_diagnostics.tracker import matrix_transition_bucket

        assert matrix_transition_bucket("l3", "l1") is None

    def test_apply_severity_returns_previous_bucket(self) -> None:
        from vibesensor.live_diagnostics._types import _TrackerLevelState
        from vibesensor.live_diagnostics.tracker import apply_severity_to_tracker

        tracker = _TrackerLevelState(current_bucket_key="l1")
        prev = apply_severity_to_tracker(tracker, 20.0, 1, 1.5)
        assert prev == "l1"


# ---------------------------------------------------------------------------
# phase_classifier: PhaseClassifier
# ---------------------------------------------------------------------------


class TestPhaseClassifier:
    """Tests for the extracted PhaseClassifier component."""

    def test_initial_phase_is_idle(self) -> None:
        from vibesensor.live_diagnostics.phase_classifier import PhaseClassifier

        pc = PhaseClassifier()
        assert pc.current_phase == "idle"

    def test_reset_returns_to_idle(self) -> None:
        from vibesensor.live_diagnostics.phase_classifier import PhaseClassifier

        pc = PhaseClassifier()
        pc.update(30.0, 1.0)
        pc.update(30.0, 2.0)
        pc.reset()
        assert pc.current_phase == "idle"

    def test_constant_speed_produces_cruise(self) -> None:
        from vibesensor.live_diagnostics.phase_classifier import PhaseClassifier

        pc = PhaseClassifier()
        for i in range(5):
            pc.update(30.0, float(i))
        assert pc.current_phase == "cruise"

    def test_increasing_speed_produces_acceleration(self) -> None:
        from vibesensor.live_diagnostics.phase_classifier import PhaseClassifier

        pc = PhaseClassifier()
        for i in range(5):
            pc.update(10.0 + i * 5.0, float(i))
        assert pc.current_phase == "acceleration"

    def test_decreasing_speed_produces_deceleration(self) -> None:
        from vibesensor.live_diagnostics.phase_classifier import PhaseClassifier

        pc = PhaseClassifier()
        for i in range(5):
            pc.update(30.0 - i * 5.0, float(i))
        assert pc.current_phase == "deceleration"

    def test_none_speed_produces_speed_unknown(self) -> None:
        from vibesensor.live_diagnostics.phase_classifier import PhaseClassifier

        pc = PhaseClassifier()
        pc.update(None, 1.0)
        assert pc.current_phase == "speed_unknown"


# ---------------------------------------------------------------------------
# event_detector: detect_sensor_events
# ---------------------------------------------------------------------------


class TestEventDetector:
    """Tests for the extracted event detection function."""

    def test_empty_clients_returns_empty(self) -> None:
        from vibesensor.live_diagnostics.event_detector import detect_sensor_events

        events = detect_sensor_events(
            speed_mps=20.0, clients=[], spectra={"clients": {}}, settings={}
        )
        assert events == []

    def test_non_dict_clients_payload_returns_empty(self) -> None:
        from vibesensor.live_diagnostics.event_detector import detect_sensor_events

        events = detect_sensor_events(
            speed_mps=20.0, clients=[], spectra={"clients": "bad"}, settings={}
        )
        assert events == []

    def test_missing_clients_key_returns_empty(self) -> None:
        from vibesensor.live_diagnostics.event_detector import detect_sensor_events

        events = detect_sensor_events(speed_mps=20.0, clients=[], spectra={}, settings={})
        assert events == []

    def test_valid_peak_produces_event(self) -> None:
        from vibesensor.live_diagnostics.event_detector import detect_sensor_events

        spectra = {
            "clients": {
                "c1": {
                    "strength_metrics": {
                        "top_peaks": [{"hz": 40.0, "amp": 0.1, "vibration_strength_db": 15.0}]
                    }
                }
            }
        }
        events = detect_sensor_events(
            speed_mps=20.0,
            clients=[{"id": "c1", "name": "front-left"}],
            spectra=spectra,
            settings={},
        )
        assert len(events) == 1
        assert events[0].sensor_id == "c1"
        assert events[0].sensor_label == "front-left"
        assert events[0].peak_hz == 40.0
        assert events[0].vibration_strength_db == 15.0

    def test_invalid_peak_skipped(self) -> None:
        from vibesensor.live_diagnostics.event_detector import detect_sensor_events

        spectra = {
            "clients": {
                "c1": {"strength_metrics": {"top_peaks": [{"hz": "not_a_number", "amp": 0.1}]}}
            }
        }
        events = detect_sensor_events(
            speed_mps=20.0,
            clients=[{"id": "c1", "name": "s1"}],
            spectra=spectra,
            settings={},
        )
        assert events == []

    def test_max_four_peaks_per_client(self) -> None:
        from vibesensor.live_diagnostics.event_detector import detect_sensor_events

        peaks = [
            {"hz": float(i * 10), "amp": 0.1, "vibration_strength_db": 10.0} for i in range(1, 10)
        ]
        spectra = {"clients": {"c1": {"strength_metrics": {"top_peaks": peaks}}}}
        events = detect_sensor_events(
            speed_mps=20.0,
            clients=[{"id": "c1", "name": "s1"}],
            spectra=spectra,
            settings={},
        )
        assert len(events) == 4


# ---------------------------------------------------------------------------
# active_levels: standalone functions
# ---------------------------------------------------------------------------


class TestActiveLevels:
    """Tests for the extracted active level management functions."""

    def test_upsert_keeps_strongest(self) -> None:
        from vibesensor.live_diagnostics.active_levels import upsert_active_level

        by_source: dict = {}
        upsert_active_level(
            active_by_source=by_source,
            source_keys=("wheel",),
            bucket_key="l2",
            strength_db=10.0,
            sensor_label="s1",
            sensor_location="front",
            class_key="wheel",
            peak_hz=30.0,
        )
        upsert_active_level(
            active_by_source=by_source,
            source_keys=("wheel",),
            bucket_key="l3",
            strength_db=20.0,
            sensor_label="s2",
            sensor_location="rear",
            class_key="wheel",
            peak_hz=31.0,
        )
        assert by_source["wheel"]["strength_db"] == 20.0
        assert by_source["wheel"]["sensor_label"] == "s2"

    def test_update_sensor_keeps_strongest(self) -> None:
        from vibesensor.live_diagnostics.active_levels import (
            update_sensor_active_level,
        )

        by_sensor: dict = {}
        update_sensor_active_level(
            by_sensor, "s1", bucket_key="l1", strength_db=5.0, class_key="wheel", peak_hz=30.0
        )
        update_sensor_active_level(
            by_sensor, "s1", bucket_key="l3", strength_db=25.0, class_key="wheel", peak_hz=31.0
        )
        assert by_sensor["s1"]["strength_db"] == 25.0

    def test_location_key_strips_whitespace(self) -> None:
        from vibesensor.live_diagnostics.active_levels import location_key

        assert location_key("  front-left  ") == "front-left"
        assert location_key("") is None
        assert location_key("  ") is None

    def test_build_active_levels_by_location_picks_dominant(self) -> None:
        from vibesensor.live_diagnostics.active_levels import (
            build_active_levels_by_location,
        )

        candidates = {
            "front-left": [
                {
                    "sensor_id": "s1",
                    "sensor_label": "s1",
                    "bucket_key": "l2",
                    "strength_db": 10.0,
                    "class_key": "wheel",
                    "peak_hz": 30.0,
                },
                {
                    "sensor_id": "s2",
                    "sensor_label": "s2",
                    "bucket_key": "l3",
                    "strength_db": 20.0,
                    "class_key": "wheel",
                    "peak_hz": 30.5,
                },
            ]
        }
        result = build_active_levels_by_location(candidates_by_location=candidates, freq_bin_hz=1.5)
        assert "front-left" in result
        assert result["front-left"]["strength_db"] == 20.0

    def test_build_active_levels_includes_agreement(self) -> None:
        from vibesensor.live_diagnostics.active_levels import (
            build_active_levels_by_location,
        )

        candidates = {
            "front": [
                {
                    "sensor_id": "s1",
                    "sensor_label": "s1",
                    "bucket_key": "l3",
                    "strength_db": 20.0,
                    "class_key": "wheel",
                    "peak_hz": 30.0,
                },
                {
                    "sensor_id": "s2",
                    "sensor_label": "s2",
                    "bucket_key": "l3",
                    "strength_db": 19.0,
                    "class_key": "wheel",
                    "peak_hz": 30.1,
                },
            ]
        }
        result = build_active_levels_by_location(candidates_by_location=candidates, freq_bin_hz=1.5)
        assert result["front"]["agreement_count"] == 2
        assert result["front"]["confidence"] == 2.0


# ---------------------------------------------------------------------------
# backward compat: verify package-level re-exports
# ---------------------------------------------------------------------------


class TestBackwardCompatReExports:
    """Verify all previously-public symbols are still importable from the package."""

    def test_engine_importable(self) -> None:
        from vibesensor.live_diagnostics import LiveDiagnosticsEngine

        assert LiveDiagnosticsEngine is not None

    def test_types_importable(self) -> None:
        from vibesensor.live_diagnostics import (
            _combine_amplitude_strength_db,
            _RecentEvent,
            _TrackerLevelState,
        )

        assert _RecentEvent is not None
        assert _TrackerLevelState is not None
        assert callable(_combine_amplitude_strength_db)

    def test_matrix_helpers_importable(self) -> None:
        from vibesensor.live_diagnostics import _copy_matrix, _new_matrix

        assert callable(_new_matrix)
        assert callable(_copy_matrix)

    def test_constants_importable(self) -> None:
        from vibesensor.live_diagnostics import SEVERITY_KEYS, SOURCE_KEYS

        assert "wheel" in SOURCE_KEYS
        assert "l3" in SEVERITY_KEYS
