"""Report and summary-warning text lookup (``data/report_i18n.json``, English and Dutch)."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache

from vibesensor.common.data_files import resolve_static_data_file
from vibesensor.common.json_types import JsonValue
from vibesensor.summary.phases import PHASE_I18N_KEYS

__all__ = [
    "format_speed",
    "is_i18n_ref",
    "normalize_lang",
    "resolve_i18n",
    "speed_unit_label",
    "tr",
]

_DATA_FILE = resolve_static_data_file("report_i18n.json")


@lru_cache(maxsize=1)
def _load_translations() -> dict[str, dict[str, str]]:
    if not _DATA_FILE.exists():
        raise RuntimeError(f"Missing translation file: {_DATA_FILE}")
    try:
        with _DATA_FILE.open(encoding="utf-8") as fh:
            data: dict[str, dict[str, str]] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid translation file: {_DATA_FILE}") from exc
    return data


def normalize_lang(lang: object) -> str:
    """Return ``"nl"`` for Dutch locale strings, ``"en"`` for everything else."""
    if isinstance(lang, str) and lang.strip().lower().startswith("nl"):
        return "nl"
    return "en"


def tr(lang: object, key: str, **kwargs: JsonValue) -> str:
    """Look up translation *key* for *lang* and format with *kwargs*."""
    values = _load_translations().get(key)
    if values is None:
        template = key
    else:
        template = values.get(normalize_lang(lang)) or values.get("en") or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def speed_unit_label(speed_unit: str, lang: object) -> str:
    """The label of the user's speed unit (``kmh`` or ``mps``), as the UI writes it."""
    if speed_unit == "mps":
        return "m/s"
    return "km/u" if normalize_lang(lang) == "nl" else "km/h"


def format_speed(kmh: float, speed_unit: str, lang: object) -> str:
    """A speed given in km/h, as a whole number in the user's unit ("85 km/h", "24 m/s")."""
    value = kmh / 3.6 if speed_unit == "mps" else kmh
    return f"{value:.0f}\u00a0{speed_unit_label(speed_unit, lang)}"


def is_i18n_ref(value: object) -> bool:
    """Check whether *value* is a language-neutral i18n reference dict."""
    return isinstance(value, dict) and "_i18n_key" in value


def resolve_i18n(lang: str, value: object, *, tr: Callable[..., str]) -> str:
    """Resolve plain strings, i18n refs, or lists of i18n refs to text."""
    if isinstance(value, list):
        return " ".join(resolve_i18n(lang, item, tr=tr) for item in value if item)
    if not isinstance(value, dict) or "_i18n_key" not in value:
        return str(value) if value is not None else ""
    key = str(value["_i18n_key"])
    suffix = str(value.get("_suffix", ""))
    params: dict[str, JsonValue] = {}
    for param_key, param_value in value.items():
        if param_key in ("_i18n_key", "_suffix"):
            continue
        if is_i18n_ref(param_value):
            params[param_key] = resolve_i18n(lang, param_value, tr=tr)
        elif param_key == "phase" and isinstance(param_value, str):
            phase_key = param_value.strip().lower().replace("-", "_").replace(" ", "_")
            i18n_key = PHASE_I18N_KEYS.get(phase_key)
            params[param_key] = tr(i18n_key) if i18n_key else param_value
        else:
            params[param_key] = param_value
    result = tr(key, **params)
    return result + suffix if suffix else result
