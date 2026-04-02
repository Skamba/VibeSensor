"""Boundary codecs for strength metrics and peak payloads."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from vibesensor.domain import StrengthMetrics, StrengthPeak
from vibesensor.shared.types.json_types import JsonObject


def strength_peak_from_mapping(payload: object) -> StrengthPeak:
    """Decode one raw peak payload into the canonical typed peak object."""

    if not isinstance(payload, Mapping):
        return StrengthPeak()
    return StrengthPeak(
        hz=_float_or(payload, "hz"),
        amp=_float_or(payload, "amp"),
        vibration_strength_db=_float_or_none(payload, "vibration_strength_db"),
        strength_bucket=_text_or_none(payload, "strength_bucket"),
    )


def strength_peaks_from_sequence(
    payload: object,
    *,
    max_items: int | None = None,
    keep_invalid: bool = False,
) -> tuple[StrengthPeak, ...]:
    """Decode a raw peak payload list into validated typed peaks."""

    if not isinstance(payload, Sequence) or isinstance(payload, str | bytes | bytearray):
        return ()
    limit = len(payload) if max_items is None else max(0, max_items)
    peaks: list[StrengthPeak] = []
    for item in payload[:limit]:
        if not isinstance(item, Mapping):
            continue
        peak = strength_peak_from_mapping(item)
        if keep_invalid or peak.is_valid:
            peaks.append(peak)
    return tuple(peaks)


def strength_peak_to_payload(peak: StrengthPeak) -> JsonObject:
    """Serialize one typed peak at an explicit JSON boundary."""

    payload: JsonObject = {
        "hz": peak.hz,
        "amp": peak.amp,
    }
    if peak.vibration_strength_db is not None:
        payload["vibration_strength_db"] = peak.vibration_strength_db
    if peak.strength_bucket is not None:
        payload["strength_bucket"] = peak.strength_bucket
    return payload


def strength_peak_payloads(
    peaks: Sequence[StrengthPeak],
    *,
    max_items: int | None = None,
) -> list[JsonObject]:
    """Serialize validated peaks at a JSON boundary."""

    items = peaks if max_items is None else peaks[: max(0, max_items)]
    return [strength_peak_to_payload(peak) for peak in items if peak.is_valid]


def strength_metrics_from_mapping(payload: object) -> StrengthMetrics:
    """Decode raw strength-metrics payloads into the canonical typed object."""

    if not isinstance(payload, Mapping):
        return StrengthMetrics()
    return StrengthMetrics(
        vibration_strength_db=_float_or_none(payload, "vibration_strength_db"),
        peak_amp_g=_float_or_none(payload, "peak_amp_g"),
        noise_floor_amp_g=_float_or_none(payload, "noise_floor_amp_g"),
        strength_bucket=_text_or_none(payload, "strength_bucket"),
        top_peaks=strength_peaks_from_sequence(payload.get("top_peaks"), keep_invalid=True),
    )


def _float_or(payload: Mapping[str, object], key: str, default: float = 0.0) -> float:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else default
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            numeric = float(text)
        except ValueError:
            return default
        return numeric if math.isfinite(numeric) else default
    return default


def _float_or_none(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = float(text)
        except ValueError:
            return None
        return numeric if math.isfinite(numeric) else None
    return None


def _text_or_none(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None
