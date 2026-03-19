"""Report internationalisation helpers.

Translation data is loaded from ``apps/server/data/report_i18n.json``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from vibesensor.domain.finding import VibrationSource
from vibesensor.shared.constants import PHASE_I18N_KEYS
from vibesensor.shared.types.json_types import JsonValue

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "report_i18n.json"


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


def tr(lang: object, key: str, **kwargs: Any) -> str:
    """Look up translation *key* for *lang* and format with *kwargs*."""
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


_logger = logging.getLogger(__name__)


def is_i18n_ref(value: object) -> bool:
    """Check whether *value* is a language-neutral i18n reference dict."""
    return isinstance(value, dict) and "_i18n_key" in value


def human_source(source: object, *, tr: Callable[[str], str]) -> str:
    """Resolve a source code to its user-facing label."""
    raw = str(source or "").strip().lower()
    mapping: dict[VibrationSource, str] = {
        VibrationSource.WHEEL_TIRE: tr("SOURCE_WHEEL_TIRE"),
        VibrationSource.DRIVELINE: tr("SOURCE_DRIVELINE"),
        VibrationSource.ENGINE: tr("SOURCE_ENGINE"),
        VibrationSource.BODY_RESONANCE: tr("SOURCE_BODY_RESONANCE"),
        VibrationSource.TRANSIENT_IMPACT: tr("SOURCE_TRANSIENT_IMPACT"),
        VibrationSource.BASELINE_NOISE: tr("SOURCE_BASELINE_NOISE"),
        VibrationSource.UNKNOWN_RESONANCE: tr("SOURCE_UNKNOWN_RESONANCE"),
        VibrationSource.UNKNOWN: tr("UNKNOWN"),
    }
    try:
        key = VibrationSource(raw)
    except ValueError:
        _logger.warning(
            "Unrecognized vibration source %r; falling back to titlecase",
            raw,
        )
        return raw.replace("_", " ").title() if raw else tr("UNKNOWN")
    return mapping.get(key, tr("UNKNOWN"))


def resolve_i18n(
    lang: str,
    value: object,
    *,
    tr: Callable[..., str],
) -> str:
    """Resolve plain strings, i18n refs, or lists of i18n refs to text."""
    if isinstance(value, list):
        return " ".join(resolve_i18n(lang, item, tr=tr) for item in value if item)
    if not isinstance(value, dict) or "_i18n_key" not in value:
        return str(value) if value is not None else ""
    key = str(value["_i18n_key"])
    suffix = str(value.get("_suffix", ""))
    params = {k: v for k, v in value.items() if k not in ("_i18n_key", "_suffix")}
    resolved_params: dict[str, JsonValue] = {}
    for param_key, param_value in params.items():
        if is_i18n_ref(param_value):
            resolved_params[param_key] = resolve_i18n(lang, param_value, tr=tr)
        elif param_key == "source" and isinstance(param_value, str):
            resolved_params[param_key] = human_source(param_value, tr=tr)
        elif param_key == "phase" and isinstance(param_value, str):
            i18n_key = PHASE_I18N_KEYS.get(param_value)
            resolved_params[param_key] = tr(i18n_key) if i18n_key else param_value
        else:
            resolved_params[param_key] = param_value
    result = tr(key, **resolved_params)
    return result + suffix if suffix else result
