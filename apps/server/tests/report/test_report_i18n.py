"""Report text catalog: complete in both languages, loaded deterministically."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibesensor.report import i18n as report_i18n

_CATALOG = Path(report_i18n.__file__).resolve().parents[1] / "data" / "report_i18n.json"


def test_every_key_has_english_and_dutch_text() -> None:
    catalog = json.loads(_CATALOG.read_text(encoding="utf-8"))

    missing = [
        key for key, values in catalog.items() if not values.get("en") or not values.get("nl")
    ]
    assert missing == []


def test_dutch_text_differs_for_report_sentences() -> None:
    catalog = json.loads(_CATALOG.read_text(encoding="utf-8"))
    sentences = [key for key, values in catalog.items() if len(values["en"].split()) >= 4]

    untranslated = [key for key in sentences if catalog[key]["en"] == catalog[key]["nl"]]
    assert untranslated == []


def test_lookup_formats_and_falls_back_to_the_key() -> None:
    assert report_i18n.tr("nl", "PAGE_OF", page=1, total=2) == "Pagina 1 van 2"
    assert report_i18n.tr("de", "PAGE_OF", page=1, total=2) == "Page 1 of 2"
    assert report_i18n.tr("en", "NO_SUCH_KEY") == "NO_SUCH_KEY"


def test_missing_catalog_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(report_i18n, "_DATA_FILE", tmp_path / "missing.json")
    report_i18n._load_translations.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Missing translation file"):
            report_i18n.tr("en", "PAGE_OF")
    finally:
        monkeypatch.undo()
        report_i18n._load_translations.cache_clear()
