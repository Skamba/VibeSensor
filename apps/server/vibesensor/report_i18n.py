# ruff: noqa: E501
"""Report internationalisation helpers.

Translation data is loaded from ``apps/server/data/report_i18n.json``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "report_i18n.json"


@lru_cache(maxsize=1)
def _load_translations() -> dict[str, dict[str, str]]:
    with open(_DATA_FILE) as fh:
        data: dict[str, dict[str, str]] = json.load(fh)
    return data


_TRANSLATIONS: dict[str, dict[str, str]] = _load_translations()


def normalize_lang(lang: object) -> str:
    if isinstance(lang, str) and lang.strip().lower().startswith("nl"):
        return "nl"
    return "en"


def tr(lang: object, key: str, **kwargs: Any) -> str:
    values = _TRANSLATIONS.get(key)
    if values is None:
        template = key
    else:
        locale = normalize_lang(lang)
        template = values.get(locale) or values.get("en") or key
    return template.format(**kwargs)


def variants(key: str) -> tuple[str, str]:
    values = _TRANSLATIONS.get(key)
    if values is None:
        return key, key
    return values.get("en", key), values.get("nl", key)
