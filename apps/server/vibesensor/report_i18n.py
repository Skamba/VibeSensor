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
    if not _DATA_FILE.exists():
        raise RuntimeError(f"Missing translation file: {_DATA_FILE}")
    try:
        with open(_DATA_FILE, encoding="utf-8") as fh:
            data: dict[str, dict[str, str]] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid translation file: {_DATA_FILE}") from exc
    return data


def normalize_lang(lang: object) -> str:
    if isinstance(lang, str) and lang.strip().lower().startswith("nl"):
        return "nl"
    return "en"


def tr(lang: object, key: str, **kwargs: Any) -> str:
    values = _load_translations().get(key)
    if values is None:
        template = key
    else:
        locale = normalize_lang(lang)
        template = values.get(locale) or values.get("en") or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template
