"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

from _paths import SERVER_ROOT

_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestExportZipFiltersInternals:
    def test_underscore_fields_stripped_in_source(self) -> None:
        """history route module must filter _-prefixed keys from analysis before export."""
        text = (SERVER_ROOT / "vibesensor" / "routes" / "history.py").read_text()
        assert 'not k.startswith("_")' in text
