"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from _paths import SERVER_ROOT

_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestAnalysisQueueMaxlen:
    def test_analysis_queue_has_maxlen(self) -> None:
        """PostAnalysisWorker._analysis_queue must have a bounded maxlen."""
        text = (SERVER_ROOT / "vibesensor" / "metrics_log" / "post_analysis.py").read_text()
        assert "_analysis_queue: deque[str] = deque(maxlen=" in text
