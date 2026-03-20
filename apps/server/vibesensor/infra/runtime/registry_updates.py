"""Protocol-level DATA message bookkeeping extracted from ``ClientRegistry``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ClientRecord

__all__ = ["DataUpdateResult", "apply_data_message_update"]

_DEDUP_WINDOW = 128
_DEDUP_RESTART_GAP = 4
_RESTART_SEQ_GAP = 1000
_JITTER_EMA_ALPHA = 0.2
_SEQ_MASK = 0xFFFFFFFF
_SEQ_HALF = 0x80000000


@dataclass(slots=True)
class DataUpdateResult:
    """Return value of :func:`apply_data_message_update`."""

    reset_detected: bool = False
    is_duplicate: bool = False


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

    if record.has_seq(seq):
        backward = (
            (record.last_seq - seq) if record.last_seq is not None and record.last_seq > seq else 0
        )
        if 0 <= backward <= _DEDUP_RESTART_GAP:
            record.duplicates_received += 1
            return DataUpdateResult(is_duplicate=True)

        record.clear_dedup()

    record.record_seq(seq)
    record.prune_seqs(_DEDUP_WINDOW)

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
            record.clear_dedup()
            record.record_seq(seq)
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
