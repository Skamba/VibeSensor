"""Runtime queue/history tracking and export-filter regressions."""

from __future__ import annotations

import pytest
from _paths import SERVER_ROOT

_DEAD_FUNCTION_CASES = [
    ("vibesensor/report/pdf_builder.py", "_measure_text_height"),
    ("vibesensor/report/pdf_diagram.py", "_amp_heat_color"),
    ("vibesensor/report/pdf_diagram.py", "def _format_db"),
    ("vibesensor/firmware_cache.py", "def install_baseline"),
]


class TestDeadFunctionsRemoved:
    @pytest.mark.parametrize(
        "rel_path, forbidden",
        _DEAD_FUNCTION_CASES,
        ids=[c[1] for c in _DEAD_FUNCTION_CASES],
    )
    def test_dead_function_absent(self, rel_path: str, forbidden: str) -> None:
        text = (SERVER_ROOT / rel_path).read_text()
        assert forbidden not in text
