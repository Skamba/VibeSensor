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


class TestPdfDiagramDeadFallback:
    """Verify the dead English fallback for SOURCE_LEGEND_TITLE was removed."""

    def test_no_inline_english_fallback(self):
        """pdf_diagram.py should not contain 'Finding source:' as a fallback."""
        assert 'else "Finding source:"' not in _PDF_DIAGRAM_SRC, (
            "Dead English fallback 'Finding source:' should be removed"
        )

    def test_tr_called_directly(self):
        """tr('SOURCE_LEGEND_TITLE') should be called without a conditional guard."""
        assert 'tr("SOURCE_LEGEND_TITLE")' in _PDF_DIAGRAM_SRC, (
            "tr('SOURCE_LEGEND_TITLE') should remain as a direct call"
        )
        # The old pattern was:
        # tr("SOURCE_LEGEND_TITLE") if tr("SOURCE_LEGEND_TITLE") != "SOURCE_LEGEND_TITLE"
        assert _PDF_DIAGRAM_SRC.count('tr("SOURCE_LEGEND_TITLE")') < 3, (
            "Should not have the old double-invocation conditional pattern"
        )
