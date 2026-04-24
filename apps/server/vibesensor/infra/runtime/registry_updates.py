"""Protocol-level DATA message bookkeeping extracted from ``ClientRegistry``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ClientRecord

__all__ = ["DataUpdateResult", "apply_data_message_update"]

_RESTART_SEQ_GAP = 1000
_JITTER_EMA_ALPHA = 0.2
_SEQ_MASK = 0xFFFFFFFF
_SEQ_HALF = 0x80000000


@dataclass(slots=True)
class DataUpdateResult:
    """Return value of :func:`apply_data_message_update`."""

    reset_detected: bool = False
    is_duplicate: bool = False
    is_late: bool = False


def _is_short_session_restart(
    record: ClientRecord,
    *,
    seq: int,
    t0_us: int,
) -> bool:
    last_seq = record.last_seq
    last_t0_us = record.last_t0_us
    return (
        last_seq is not None
        and last_t0_us is not None
        and seq <= last_seq
        and t0_us > last_t0_us
        and (last_seq - seq) < _RESTART_SEQ_GAP
    )


def _is_seq_behind(*, seq: int, last_seq: int) -> bool:
    return seq != last_seq and ((last_seq - seq) & _SEQ_MASK) < _SEQ_HALF


def _is_late_packet(
    record: ClientRecord,
    *,
    seq: int,
    t0_us: int,
) -> bool:
    last_seq = record.last_seq
    last_t0_us = record.last_t0_us
    return (
        last_seq is not None
        and last_t0_us is not None
        and _is_seq_behind(seq=seq, last_seq=last_seq)
        and t0_us <= last_t0_us
    )


def apply_data_message_update(
    record: ClientRecord,
    *,
    seq: int,
    sample_count: int,
    t0_us: int,
    addr: tuple[str, int],
    now_ts: float,
    mono: float,
) -> DataUpdateResult:
    """Apply one DATA message to an existing client record."""

    record.last_seen = now_ts
    record.last_seen_mono = mono
    record.data_addr = (addr[0], addr[1])

    if _is_short_session_restart(record, seq=seq, t0_us=t0_us):
        # A restarted short-lived sender can reuse low sequence numbers with a
        # strictly newer t0_us before the large-gap reset heuristic fires.
        record.dedup_window.clear()
        record.last_seq = None
        record.last_t0_us = None
        record.timing_jitter_us_ema = 0.0
        record.timing_drift_us_total = 0.0

    if record.dedup_window.track(seq):
        record.duplicates_received += 1
        return DataUpdateResult(is_duplicate=True)
    if _is_late_packet(record, seq=seq, t0_us=t0_us):
        return DataUpdateResult(is_late=True)

    record.frames_total += 1
    reset_detected = False
    if (
        record.sample_rate_hz > 0
        and sample_count > 0
        and record.last_t0_us is not None
        and t0_us >= record.last_t0_us
    ):
        expected_delta_us = (float(sample_count) / float(record.sample_rate_hz)) * 1_000_000.0
        actual_delta_us = float(t0_us - record.last_t0_us)
        jitter_us = actual_delta_us - expected_delta_us
        record.timing_jitter_us_ema = (
            1.0 - _JITTER_EMA_ALPHA
        ) * record.timing_jitter_us_ema + _JITTER_EMA_ALPHA * jitter_us
        record.timing_drift_us_total += jitter_us

    if record.last_seq is not None:
        if seq < record.last_seq and (record.last_seq - seq) > _RESTART_SEQ_GAP:
            record.reset_count += 1
            record.last_reset_time = now_ts
            record.last_t0_us = None
            record.timing_jitter_us_ema = 0.0
            record.timing_drift_us_total = 0.0
            record.dedup_window.clear()
            record.dedup_window.track(seq)
            reset_detected = True
        else:
            expected = (record.last_seq + 1) & _SEQ_MASK
            if seq != expected:
                gap = (seq - expected) & _SEQ_MASK
                if gap < _SEQ_HALF:
                    record.frames_dropped += gap

    if record.last_seq is None or ((seq - record.last_seq) & _SEQ_MASK) < _SEQ_HALF:
        record.last_seq = seq
    record.last_t0_us = t0_us
    return DataUpdateResult(reset_detected=reset_detected)
