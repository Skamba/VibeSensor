"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from _paths import SERVER_ROOT

_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestNormalizeLangArchitecturalBoundary:
    _SUMMARY_SRC = SERVER_ROOT / "vibesensor" / "analysis" / "summary.py"

    def test_summary_does_not_import_report_i18n(self) -> None:
        """summary.py must NOT import from report_i18n (i18n separation constraint)."""
        assert "from ..report_i18n import" not in self._SUMMARY_SRC.read_text()

    def test_summary_has_inline_normalize_lang(self) -> None:
        """summary.py must define its own _normalize_lang (avoiding report_i18n dep)."""
        assert "def _normalize_lang" in self._SUMMARY_SRC.read_text()
