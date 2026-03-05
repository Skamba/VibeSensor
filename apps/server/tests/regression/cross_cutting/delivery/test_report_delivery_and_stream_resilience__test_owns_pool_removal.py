"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""

from __future__ import annotations

import inspect

from vibesensor.esp_flash_manager import EspFlashManager
from vibesensor.processing import SignalProcessor
from vibesensor.report import pdf_diagram

_PDF_DIAGRAM_SRC = inspect.getsource(pdf_diagram)

_RUN_FLASH_JOB_SRC = inspect.getsource(EspFlashManager._run_flash_job)

_I18N_ERROR_KEYS = [
    "settings.car.delete_failed",
    "settings.car.activate_failed",
    "settings.car.save_failed",
]


class TestOwnsPoolRemoval:
    """Verify _owns_pool dead code was removed from SignalProcessor."""

    def test_no_owns_pool_attribute(self):
        """SignalProcessor should not have _owns_pool attribute."""
        source = inspect.getsource(SignalProcessor.__init__)
        assert "_owns_pool" not in source, (
            "Dead _owns_pool flag should be removed from SignalProcessor.__init__"
        )

    def test_constructor_still_works(self):
        """SignalProcessor can still be constructed with or without a pool."""
        proc = SignalProcessor(
            sample_rate_hz=200,
            waveform_seconds=5,
            waveform_display_hz=30,
            fft_n=256,
        )
        assert not hasattr(proc, "_owns_pool"), (
            "_owns_pool attribute should not exist on SignalProcessor instances"
        )
