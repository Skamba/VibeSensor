from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor import report_i18n


def test_translation_loads_and_translates() -> None:
    assert report_i18n.tr("nl", "REPORT_DATE") != "REPORT_DATE"


def test_missing_translation_file_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_i18n, "_DATA_FILE", Path("/definitely/missing/report_i18n.json"))
    report_i18n._load_translations.cache_clear()
    with pytest.raises(RuntimeError, match="Missing translation file"):
        report_i18n.tr("en", "REPORT_DATE")


def test_corrupt_translation_file_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "report_i18n.json"
    broken.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(report_i18n, "_DATA_FILE", broken)
    report_i18n._load_translations.cache_clear()
    with pytest.raises(RuntimeError, match="Invalid translation file"):
        report_i18n.tr("en", "REPORT_DATE")
