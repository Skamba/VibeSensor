"""Shared i18n and value-resolution helpers for report-data mapping."""

from __future__ import annotations

from collections.abc import Callable

from ...runlog import as_float_or_none as _as_float
from .._types import Finding, JsonValue, TopCause
from ..helpers import PHASE_I18N_KEYS

_ORDER_LABEL_NAMES_NL: dict[str, str] = {
    "wheel": "wielorde",
    "engine": "motororde",
    "driveshaft": "aandrijfasorde",
}
_ORDER_LABEL_NAMES_DEFAULT: dict[str, str] = {
    "wheel": "wheel order",
    "engine": "engine order",
    "driveshaft": "driveshaft order",
}

_CLASSIFICATION_I18N_KEYS: dict[str, str] = {
    "patterned": "CLASSIFICATION_PATTERNED",
    "persistent": "CLASSIFICATION_PERSISTENT",
    "transient": "CLASSIFICATION_TRANSIENT",
    "baseline_noise": "CLASSIFICATION_BASELINE_NOISE",
}


def is_i18n_ref(value: object) -> bool:
    """Check whether *value* is a language-neutral i18n reference dict."""
    return isinstance(value, dict) and "_i18n_key" in value


def human_source(source: object, *, tr: Callable[[str], str]) -> str:
    """Resolve a source code to its user-facing label."""
    raw = str(source or "").strip().lower()
    mapping = {
        "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
        "driveline": tr("SOURCE_DRIVELINE"),
        "engine": tr("SOURCE_ENGINE"),
        "body resonance": tr("SOURCE_BODY_RESONANCE"),
        "transient_impact": tr("SOURCE_TRANSIENT_IMPACT"),
        "baseline_noise": tr("SOURCE_BASELINE_NOISE"),
        "unknown_resonance": tr("SOURCE_UNKNOWN_RESONANCE"),
        "unknown": tr("UNKNOWN"),
    }
    return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))


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


def order_label_human(lang: str, label: str) -> str:
    """Translate a language-neutral order label like ``1x wheel``."""
    names = _ORDER_LABEL_NAMES_NL if lang == "nl" else _ORDER_LABEL_NAMES_DEFAULT
    parts = label.strip().split(" ", 1)
    if len(parts) == 2:
        multiplier, base = parts
        localized = names.get(base.lower(), base)
        return f"{multiplier} {localized}"
    return label


def peak_classification_text(value: object, tr: Callable[..., str]) -> str:
    """Map a peak classification code to report text."""
    normalized = str(value or "").strip().lower()
    i18n_key = _CLASSIFICATION_I18N_KEYS.get(normalized)
    if i18n_key:
        return tr(i18n_key)
    if not normalized:
        return tr("UNKNOWN")
    return str(value).replace("_", " ").title()


def extract_confidence(item: Finding | TopCause) -> float:
    """Return the confidence value from a cause/finding dict."""
    value = _as_float(item.get("confidence"))
    if value is None:
        value = _as_float(item.get("confidence_0_to_1"))
    return value if value is not None else 0.0


def finding_strength_db(finding: Finding) -> float | None:
    """Extract a finding's vibration-strength dB value if present."""
    evidence_metrics = finding.get("evidence_metrics")
    return (
        _as_float(evidence_metrics.get("vibration_strength_db"))
        if isinstance(evidence_metrics, dict)
        else None
    )
