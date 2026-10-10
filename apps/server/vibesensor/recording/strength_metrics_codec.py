"""Boundary codecs for strength metrics and peak payloads."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import msgspec

from vibesensor.common.json_types import JsonObject
from vibesensor.common.scalars import float_or, optional_float, text_or_none
from vibesensor.domain.strength_metrics import StrengthMetrics, StrengthPeak

_INF = math.inf
# Decodes a stored peak list straight into typed peaks; it rejects what the
# generic decode would coerce (null, text or out-of-range numbers, non-objects).
_STORED_PEAKS_DECODER = msgspec.json.Decoder(list[StrengthPeak])


class _StoredPeakLevel(msgspec.Struct):
    """The fields of a stored peak that say where and how loud it is."""

    hz: float = 0.0
    amp: float = 0.0


_STORED_PEAK_LEVELS_DECODER = msgspec.json.Decoder(list[_StoredPeakLevel])


def _finite_or_absent(value: object) -> bool:
    return value is None or (type(value) is float and -_INF < value < _INF)


def _clean_text_or_absent(value: object) -> bool:
    return value is None or (type(value) is str and value != "" and value.strip() == value)


def strength_peak_from_mapping(payload: object) -> StrengthPeak:
    """Decode one raw peak payload into the canonical typed peak object."""

    if type(payload) is dict:
        # The common case (peaks the analysis or a stored row produced): finite
        # floats and a clean bucket name, which the general path keeps unchanged.
        hz = payload.get("hz")
        amp = payload.get("amp")
        strength_db = payload.get("vibration_strength_db")
        bucket = payload.get("strength_bucket")
        local_floor = payload.get("local_floor_amp_g")
        if (
            type(hz) is float
            and -_INF < hz < _INF
            and type(amp) is float
            and -_INF < amp < _INF
            and _finite_or_absent(strength_db)
            and _finite_or_absent(local_floor)
            and _clean_text_or_absent(bucket)
        ):
            return StrengthPeak(hz, amp, strength_db, bucket, local_floor)
    if not isinstance(payload, Mapping):
        return StrengthPeak()
    return StrengthPeak(
        hz=float_or(payload.get("hz")),
        amp=float_or(payload.get("amp")),
        vibration_strength_db=optional_float(payload.get("vibration_strength_db")),
        strength_bucket=text_or_none(payload.get("strength_bucket")),
        local_floor_amp_g=optional_float(payload.get("local_floor_amp_g")),
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


def stored_strength_peaks(text: str, *, max_items: int) -> tuple[StrengthPeak, ...] | None:
    """The valid peaks among the first *max_items* of a stored JSON peak list.

    Equal to ``strength_peaks_from_sequence(json.loads(text), max_items=max_items)``
    whenever it returns peaks. ``None`` means *text* is not a list of well-formed
    peaks (bad JSON, a non-object item, a null or text number, an untrimmed
    bucket name); the caller then takes the general path, which coerces those.
    """
    try:
        peaks = _STORED_PEAKS_DECODER.decode(text)
    except msgspec.DecodeError:
        return None
    # ``StrengthPeak.is_valid``, inline: it runs per peak of every stored row.
    kept = [peak for peak in peaks[: max(0, max_items)] if peak.hz > 0.0 and peak.amp > 0.0]
    for peak in kept:
        if not _clean_text_or_absent(peak.strength_bucket):
            return None
    return tuple(kept)


def stored_strength_peak_amps(text: str, *, max_items: int) -> list[float] | None:
    """The amplitudes of the peaks ``stored_strength_peaks`` keeps, decoding only those.

    ``None`` means *text* is not a list of peaks with numeric ``hz`` and ``amp``.
    """
    try:
        peaks = _STORED_PEAK_LEVELS_DECODER.decode(text)
    except msgspec.DecodeError:
        return None
    return [peak.amp for peak in peaks[: max(0, max_items)] if peak.hz > 0.0 and peak.amp > 0.0]


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
    if peak.local_floor_amp_g is not None:
        payload["local_floor_amp_g"] = peak.local_floor_amp_g
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
