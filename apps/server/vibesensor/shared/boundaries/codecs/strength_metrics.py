"""Boundary codecs for strength metrics and peak payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.domain import StrengthMetrics, StrengthPeak
from vibesensor.shared.boundaries.codecs.scalars import float_or, optional_float, text_or_none
from vibesensor.shared.types.json_types import JsonObject


def strength_peak_from_mapping(payload: object) -> StrengthPeak:
    """Decode one raw peak payload into the canonical typed peak object."""

    if not isinstance(payload, Mapping):
        return StrengthPeak()
    return StrengthPeak(
        hz=float_or(payload.get("hz")),
        amp=float_or(payload.get("amp")),
        vibration_strength_db=optional_float(payload.get("vibration_strength_db")),
        strength_bucket=text_or_none(payload.get("strength_bucket")),
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
        vibration_strength_db=optional_float(payload.get("vibration_strength_db")),
        peak_amp_g=optional_float(payload.get("peak_amp_g")),
        noise_floor_amp_g=optional_float(payload.get("noise_floor_amp_g")),
        strength_bucket=text_or_none(payload.get("strength_bucket")),
        top_peaks=strength_peaks_from_sequence(payload.get("top_peaks"), keep_invalid=True),
    )
