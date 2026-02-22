from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vibesensor import report_i18n

_I18N_JSON = Path(__file__).resolve().parent.parent / "data" / "report_i18n.json"
_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "vibesensor"


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


def test_all_json_keys_have_en_and_nl() -> None:
    data = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    missing: list[str] = []
    for key, translations in data.items():
        for lang in ("en", "nl"):
            val = translations.get(lang)
            if not isinstance(val, str) or not val.strip():
                missing.append(f"{key}.{lang}")
    assert missing == [], f"Keys with missing or empty translations: {missing}"


def test_all_source_referenced_keys_exist_in_json() -> None:
    data = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    # Match _tr(lang, "KEY") and tr("KEY") calls – the two i18n call patterns used.
    pattern = re.compile(r'(?:_tr\([^,]+,|(?<!\w)tr\()\s*"([A-Z][A-Z_0-9]+)"')
    referenced_keys: set[str] = set()
    for py_file in _SOURCE_ROOT.rglob("*.py"):
        for match in pattern.finditer(py_file.read_text(encoding="utf-8")):
            referenced_keys.add(match.group(1))
    assert referenced_keys, "Sanity: should find at least some keys"
    missing = sorted(referenced_keys - set(data.keys()))
    assert missing == [], f"Keys referenced in source but missing from JSON: {missing}"


def test_variants_returns_both_languages() -> None:
    en_text, nl_text = report_i18n.variants("REPORT_DATE")
    assert isinstance(en_text, str) and en_text.strip()
    assert isinstance(nl_text, str) and nl_text.strip()
    assert en_text != nl_text


def test_dutch_translation_corrections() -> None:
    assert report_i18n.tr("nl", "HEAT_LEGEND_MORE") == "Meer trilling"
    assert report_i18n.tr("nl", "RUN_TRIAGE") == "Run triage"
    assert (
        report_i18n.tr("nl", "COVERAGE_RISES_ABOVE_THRESHOLD_AND_WHEEL_ORDER_CHECKS")
        == "Dekking stijgt boven de drempel en wielorde-controles komen beschikbaar."
    )
    assert (
        report_i18n.tr("nl", "ENGINE_ORDER_CHECKS_BECOME_AVAILABLE_WITH_ADEQUATE_RPM")
        == "Motororde-controles komen beschikbaar bij voldoende toerentaldekking."
    )
