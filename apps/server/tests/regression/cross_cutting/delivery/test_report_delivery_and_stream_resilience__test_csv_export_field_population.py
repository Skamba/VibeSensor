"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""

from __future__ import annotations

import inspect
import json

from vibesensor.api import _flatten_for_csv
from vibesensor.esp_flash_manager import EspFlashManager
from vibesensor.report import pdf_diagram

_PDF_DIAGRAM_SRC = inspect.getsource(pdf_diagram)

_RUN_FLASH_JOB_SRC = inspect.getsource(EspFlashManager._run_flash_job)

_I18N_ERROR_KEYS = [
    "settings.car.delete_failed",
    "settings.car.activate_failed",
    "settings.car.save_failed",
]


class TestCsvExportFieldPopulation:
    """Verify _flatten_for_csv populates record_type and schema_version."""

    def test_empty_row_gets_defaults(self):
        """A row with no record_type/schema_version gets them populated."""
        result = _flatten_for_csv({"accel_x_g": 0.5, "t_s": 1.0})
        assert result["record_type"] == "sample"
        assert result["schema_version"] == "2"

    def test_existing_values_preserved(self):
        """If record_type/schema_version are already in the row, keep them."""
        result = _flatten_for_csv({"record_type": "meta", "schema_version": "3"})
        assert result["record_type"] == "meta"
        assert result["schema_version"] == "3"

    def test_extras_still_work(self):
        """Non-column keys are still collected into extras."""
        result = _flatten_for_csv({"accel_x_g": 0.5, "custom_field": "hello"})
        assert result["record_type"] == "sample"
        assert "extras" in result
        extras = json.loads(result["extras"])
        assert extras["custom_field"] == "hello"

    def test_list_values_json_serialized(self):
        """List/dict values in known columns are JSON-serialized."""
        result = _flatten_for_csv({"top_peaks": [1, 2, 3]})
        assert result["top_peaks"] == "[1, 2, 3]"
        assert result["record_type"] == "sample"
