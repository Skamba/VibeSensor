"""Report internationalisation helpers.

Translation data is loaded from ``apps/server/vibesensor/data/report_i18n.json``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache

from vibesensor.shared._data_files import resolve_static_data_file
from vibesensor.shared.constants.phases import PHASE_I18N_KEYS
from vibesensor.shared.types.json_types import JsonValue

_DATA_FILE = resolve_static_data_file("report_i18n.json")
type _LocationLabels = tuple[str, str, str, str]
_LOCATION_LABEL_DEFS: tuple[tuple[tuple[str, ...], _LocationLabels], ...] = (
    (
        (
            "front left",
            "front left wheel",
            "front_left",
            "front_left_wheel",
            "front-left",
            "front-left wheel",
            "linksvoor",
            "voor links",
            "linkervoorwiel",
            "voorwiel links",
        ),
        ("Front-Left", "Front Left", "Linksvoor", "wiel linksvoor"),
    ),
    (
        (
            "front right",
            "front right wheel",
            "front_right",
            "front_right_wheel",
            "front-right",
            "front-right wheel",
            "rechtsvoor",
            "voor rechts",
            "rechtervoorwiel",
            "voorwiel rechts",
        ),
        ("Front-Right", "Front Right", "Rechtsvoor", "wiel rechtsvoor"),
    ),
    (
        (
            "rear left",
            "rear left wheel",
            "rear_left",
            "rear_left_wheel",
            "rear-left",
            "rear-left wheel",
            "linksachter",
            "achter links",
            "linkerachterwiel",
            "achterwiel links",
        ),
        ("Rear-Left", "Rear Left", "Linksachter", "wiel linksachter"),
    ),
    (
        (
            "rear right",
            "rear right wheel",
            "rear_right",
            "rear_right_wheel",
            "rear-right",
            "rear-right wheel",
            "rechtsachter",
            "achter rechts",
            "rechterachterwiel",
            "achterwiel rechts",
        ),
        ("Rear-Right", "Rear Right", "Rechtsachter", "wiel rechtsachter"),
    ),
)


def _location_label_key(value: object) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


_LOCATION_LABELS: dict[str, _LocationLabels] = {}
for aliases, labels in _LOCATION_LABEL_DEFS:
    for alias in aliases:
        _LOCATION_LABELS[_location_label_key(alias)] = labels

_AMBIGUOUS_LOCATION_PREFIX = "ambiguous location:"
_BODY_LIKE_LOCATION_TOKENS = {"body", "cabin", "trunk"}


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
        locale = normalize_lang(lang)
        template = values.get(locale) or values.get("en") or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def is_i18n_ref(value: object) -> bool:
    """Check whether *value* is a language-neutral i18n reference dict."""
    return isinstance(value, dict) and "_i18n_key" in value


def human_location(location: object, *, short: bool = True, lang: object = "en") -> str:
    """Resolve a location value to a stable human-facing label."""
    raw = str(location or "").strip()
    if not raw:
        return "Onbekend" if normalize_lang(lang) == "nl" else "Unknown"
    labels = _LOCATION_LABELS.get(_location_label_key(raw))
    if labels is not None:
        en_short, en_full, nl_short, nl_full = labels
        if normalize_lang(lang) == "nl":
            return nl_short if short else nl_full
        return en_short if short else en_full
    title = " ".join(part for part in _location_label_key(raw).split() if part)
    if not title:
        return "Onbekend" if normalize_lang(lang) == "nl" else "Unknown"
    if normalize_lang(lang) == "nl":
        return title[:1].upper() + title[1:]
    return title.title()


def location_candidates(location: object) -> tuple[str, ...]:
    """Split a report location into distinct location candidates."""
    raw = str(location or "").strip()
    if not raw:
        return ()
    normalized = raw
    if raw.lower().startswith(_AMBIGUOUS_LOCATION_PREFIX):
        normalized = raw.split(":", maxsplit=1)[1].strip()
    parts = [part.strip() for part in normalized.split("/") if part.strip()]
    unique_parts: list[str] = []
    for part in parts or [normalized]:
        if part and part not in unique_parts:
            unique_parts.append(part)
    return tuple(unique_parts)


def is_composite_location(location: object) -> bool:
    """Whether a location encodes multiple competing candidates."""
    return len(location_candidates(location)) > 1


def is_body_like_location(location: object) -> bool:
    """Whether a location points to a broad body/cabin area, not a precise part."""
    for candidate in location_candidates(location):
        normalized = candidate.lower().replace("_", " ").replace("-", " ")
        if _BODY_LIKE_LOCATION_TOKENS.intersection(normalized.split()):
            return True
    return False


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
            from vibesensor.shared.report_presentation import human_source

            resolved_params[param_key] = human_source(param_value, tr=tr)
        elif param_key == "phase" and isinstance(param_value, str):
            phase_key = param_value.strip().lower().replace("-", "_").replace(" ", "_")
            i18n_key = PHASE_I18N_KEYS.get(phase_key)
            resolved_params[param_key] = tr(i18n_key) if i18n_key else param_value
        else:
            resolved_params[param_key] = param_value
    result = tr(key, **resolved_params)
    return result + suffix if suffix else result
