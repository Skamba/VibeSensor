"""Report/export resilience regressions: EspFlashManager CancelledError, PDF diagram
dead fallback removal, PDF diagram ValueError, dead _owns_pool removal,
report_cli error handling, WebSocketHub circuit breaker,
CSV export record_type/schema_version population."""

from __future__ import annotations

import inspect
import json

import pytest
from _paths import REPO_ROOT

from vibesensor.esp_flash_manager import EspFlashManager
from vibesensor.report import pdf_diagram

_PDF_DIAGRAM_SRC = inspect.getsource(pdf_diagram)

_RUN_FLASH_JOB_SRC = inspect.getsource(EspFlashManager._run_flash_job)

_I18N_ERROR_KEYS = [
    "settings.car.delete_failed",
    "settings.car.activate_failed",
    "settings.car.save_failed",
]


class TestCarErrorI18nKeys:
    """Verify i18n keys for car error feedback exist in both catalogs."""

    @pytest.mark.parametrize("key", _I18N_ERROR_KEYS)
    @pytest.mark.parametrize("lang", ["en", "nl"])
    def test_i18n_key_exists(self, lang, key):
        catalog_path = REPO_ROOT / "apps" / "ui" / "src" / "i18n" / "catalogs" / f"{lang}.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert key in catalog, f"Missing i18n key {key!r} in {lang}.json"
