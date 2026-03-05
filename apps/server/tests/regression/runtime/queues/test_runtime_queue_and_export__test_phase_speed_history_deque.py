"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from collections import deque

from vibesensor.live_diagnostics import LiveDiagnosticsEngine

_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestPhaseSpeedHistoryDeque:
    def test_is_deque_with_maxlen(self) -> None:
        engine = LiveDiagnosticsEngine()
        assert isinstance(engine._phase_speed_history, deque)
        assert engine._phase_speed_history.maxlen is not None
        assert engine._phase_speed_history.maxlen > 0

    def test_reset_preserves_deque(self) -> None:
        engine = LiveDiagnosticsEngine()
        engine.reset()
        assert isinstance(engine._phase_speed_history, deque)
        assert engine._phase_speed_history.maxlen is not None
