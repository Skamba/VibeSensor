"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from vibesensor.live_diagnostics import LiveDiagnosticsEngine, _TrackerLevelState

_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestSensorTrackersPruning:
    def test_stale_trackers_are_pruned(self) -> None:
        """Trackers not seen for many ticks should be removed."""
        engine = LiveDiagnosticsEngine()
        engine._sensor_trackers["stale:key"] = _TrackerLevelState()
        # Simulate 60 ticks of silence (not in seen set)
        for _ in range(60):
            engine._decay_unseen_sensor_trackers(set())
        assert "stale:key" not in engine._sensor_trackers

    def test_seen_trackers_not_pruned(self) -> None:
        engine = LiveDiagnosticsEngine()
        engine._sensor_trackers["active:key"] = _TrackerLevelState()
        for _ in range(100):
            engine._decay_unseen_sensor_trackers({"active:key"})
        assert "active:key" in engine._sensor_trackers
