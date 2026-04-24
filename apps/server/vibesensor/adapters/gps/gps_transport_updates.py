"""GPS transport ingest and snapshot-update policy."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from vibesensor.adapters.gps.gpsd_message_handler import (
    GpsdVersionInfo,
    NormalizedTpvData,
    classify_gpsd_message,
    read_non_negative_metric,
    read_tpv_mode,
)
from vibesensor.adapters.gps.speed_validation import evaluate_speed_sample, is_speed_plausible
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.timed_observation import append_timed_observation
from vibesensor.shared.types.json_types import JsonObject

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_transport import GPSTransportSnapshot

TpvModeReader = Callable[[JsonObject], int | None]
MetricReader = Callable[[JsonObject, str], float | None]
MonotonicReader = Callable[[], float]


class MutableTransportState(Protocol):
    """Minimal transport-state seam required by ingest/update policy."""

    def snapshot(self) -> GPSTransportSnapshot: ...

    def _replace_transport(self, **changes: object) -> None: ...


def normalize_optional_float(value: object) -> float | None:
    """Normalize arbitrary numeric input to a finite float or ``None``."""
    if value is None or isinstance(value, bool) or not isinstance(value, NUMERIC_TYPES):
        return None
    numeric_value = float(value)
    return numeric_value if math.isfinite(numeric_value) else None


def normalize_speed_snapshot(
    value: tuple[float | None, float | None],
) -> tuple[float | None, float | None]:
    """Normalize the speed/timestamp pair stored on the transport snapshot."""
    speed, timestamp = value
    return (
        normalize_optional_float(speed),
        normalize_optional_float(timestamp),
    )


def evaluate_snapshot_speed_sample(
    snapshot: GPSTransportSnapshot,
    speed_mps: float,
) -> tuple[bool, int]:
    """Evaluate one speed sample against the current transport snapshot."""
    verdict = evaluate_speed_sample(
        speed_mps,
        snapshot.speed_snapshot[0],
        snapshot.zero_speed_streak,
    )
    return verdict.accepted, verdict.zero_speed_streak


def accept_speed_sample(
    state: MutableTransportState,
    speed_mps: float,
) -> bool:
    """Update the zero-speed streak on *state* and return whether the sample is accepted."""
    accepted, zero_speed_streak = evaluate_snapshot_speed_sample(state.snapshot(), speed_mps)
    state._replace_transport(zero_speed_streak=zero_speed_streak)
    return accepted


def reset_fix_metadata(state: MutableTransportState) -> None:
    """Clear all fix metadata fields on the transport snapshot."""
    state._replace_transport(
        last_fix_mode=None,
        last_epx_m=None,
        last_epy_m=None,
        last_epv_m=None,
        zero_speed_streak=0,
        speed_snapshot=(None, None),
        device_info=None,
    )


def classify_transport_message(
    payload: JsonObject,
    *,
    tpv_mode: TpvModeReader | None = None,
    read_metric: MetricReader | None = None,
) -> GpsdVersionInfo | NormalizedTpvData | None:
    """Classify one GPSD payload for transport-side handling."""
    if payload.get("class") == "TPV" and (tpv_mode is not None or read_metric is not None):
        return normalize_tpv_payload(
            payload,
            tpv_mode=tpv_mode,
            read_metric=read_metric,
        )
    message = classify_gpsd_message(payload)
    return message


def apply_tpv(
    state: MutableTransportState,
    tpv: NormalizedTpvData,
    *,
    monotonic: MonotonicReader,
) -> None:
    """Apply normalized TPV data to the transport snapshot."""
    snapshot = state.snapshot()
    speed_snapshot = snapshot.speed_snapshot
    zero_speed_streak = snapshot.zero_speed_streak

    if isinstance(tpv.mode, int) and tpv.mode >= 2 and tpv.speed is not None:
        if is_speed_plausible(tpv.speed):
            accepted, zero_speed_streak = evaluate_snapshot_speed_sample(snapshot, tpv.speed)
            if accepted:
                observed_at = monotonic()
                speed_snapshot = (tpv.speed, observed_at)
                speed_history = append_timed_observation(
                    snapshot.speed_history,
                    value=tpv.speed,
                    monotonic_s=observed_at,
                    now_s=observed_at,
                )
            else:
                speed_history = snapshot.speed_history
        else:
            zero_speed_streak = 0
            speed_history = snapshot.speed_history
    else:
        zero_speed_streak = 0
        speed_history = snapshot.speed_history

    device_info = tpv.device if tpv.device else snapshot.device_info
    state._replace_transport(
        last_fix_mode=tpv.mode,
        last_epx_m=tpv.epx,
        last_epy_m=tpv.epy,
        last_epv_m=tpv.epv,
        speed_snapshot=speed_snapshot,
        speed_history=speed_history,
        zero_speed_streak=zero_speed_streak,
        device_info=device_info,
    )


def normalize_tpv_payload(
    payload: JsonObject,
    *,
    tpv_mode: TpvModeReader | None = None,
    read_metric: MetricReader | None = None,
) -> NormalizedTpvData:
    """Normalize a raw TPV payload into the typed transport-update input."""
    read_mode = read_tpv_mode if tpv_mode is None else tpv_mode
    metric_reader = read_non_negative_metric if read_metric is None else read_metric

    speed = payload.get("speed")
    normalized_speed: float | None = None
    if isinstance(speed, NUMERIC_TYPES) and not isinstance(speed, bool):
        speed_f = float(speed)
        if math.isfinite(speed_f):
            normalized_speed = speed_f

    device = payload.get("device")
    normalized_device = device if isinstance(device, str) and device else None
    return NormalizedTpvData(
        mode=read_mode(payload),
        speed=normalized_speed,
        epx=metric_reader(payload, "epx"),
        epy=metric_reader(payload, "epy"),
        epv=metric_reader(payload, "epv"),
        device=normalized_device,
    )
