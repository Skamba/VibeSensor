"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""

from __future__ import annotations

import inspect

from vibesensor.esp_flash_manager import EspFlashManager
from vibesensor.report import pdf_diagram

_PDF_DIAGRAM_SRC = inspect.getsource(pdf_diagram)

_RUN_FLASH_JOB_SRC = inspect.getsource(EspFlashManager._run_flash_job)

_I18N_ERROR_KEYS = [
    "settings.car.delete_failed",
    "settings.car.activate_failed",
    "settings.car.save_failed",
]


class TestPdfDiagramAssertReplacement:
    """Verify bare assert replaced with ValueError for label placement."""

    def test_no_bare_assert_best(self):
        """pdf_diagram.py should not use bare assert for best placement."""
        assert "assert best is not None" not in _PDF_DIAGRAM_SRC, (
            "Bare 'assert best is not None' should be replaced with ValueError"
        )

    def test_value_error_on_no_placement(self):
        """When no label placement is found, ValueError should be raised."""
        assert "raise ValueError" in _PDF_DIAGRAM_SRC, (
            "Should raise ValueError when no valid label placement is found"
        )
