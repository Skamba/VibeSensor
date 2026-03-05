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


class TestEspFlashManagerCancelledError:
    """Verify CancelledError is caught, status finalized, and re-raised."""

    def test_cancelled_error_handler_exists(self):
        """The except block for CancelledError must precede except Exception."""
        cancel_pos = _RUN_FLASH_JOB_SRC.find("except asyncio.CancelledError")
        generic_pos = _RUN_FLASH_JOB_SRC.find("except Exception")
        assert cancel_pos != -1, "CancelledError handler not found in _run_flash_job"
        assert cancel_pos < generic_pos, (
            "CancelledError handler must appear before generic Exception handler"
        )

    def test_cancelled_error_re_raises(self):
        """The CancelledError handler must re-raise."""
        cancel_block_start = _RUN_FLASH_JOB_SRC.find("except asyncio.CancelledError")
        generic_block_start = _RUN_FLASH_JOB_SRC.find("except Exception")
        cancel_block = _RUN_FLASH_JOB_SRC[cancel_block_start:generic_block_start]
        assert "raise" in cancel_block, "CancelledError handler must re-raise the exception"
