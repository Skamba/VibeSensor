"""Client registry — tracks active ESP32 sensor clients.

Maintains per-client state (sequence numbers, dedup windows, last-seen
timestamps, transport-error counters), applies HELLO/DATA/ACK bookkeeping,
owns the live/retained/stale liveness policy, and projects raw client
snapshots for transport presenters. User-assigned client names live in
``client_metadata``.
"""

from __future__ import annotations

import copy
import logging
import math
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Literal

from vibesensor.common.recent_counter import RECENT_WINDOW_S, RecentCounter
from vibesensor.domain.sensor import normalize_sensor_id
from vibesensor.ingest.client_metadata import ClientMetadataManager
from vibesensor.ingest.sensor_timing import SensorTimingGuard
from vibesensor.live.payload_types import ClientMetrics
from vibesensor.settings.location_assignment_validator import (
    AssignedLocation,
    LocationAssignmentValidator,
)

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB
    from vibesensor.ingest.protocol_messages import AckMessage, DataMessage, HelloMessage

LOGGER = logging.getLogger(__name__)
_LOCATION_VALIDATOR = LocationAssignmentValidator()

__all__ = [
    "ClientLivenessPolicy",
    "ClientRecord",
    "ClientRegistry",
    "ClientSnapshot",
    "DataUpdateResult",
    "DedupWindow",
    "ExpectedFrameLoss",
    "apply_data_message_update",
    "project_client_snapshots",
]

_DEFAULT_DEDUP_WINDOW_SIZE = 128
_RESTART_SEQ_GAP = 1000
# A sensor that reboots restarts its sequence counter and its device clock; until
# the server's clock offset is re-applied (up to ~2 s, at its next HELLO or sync
# broadcast) its t0_us is far behind the previous session. Genuine late/reordered UDP frames are
# only milliseconds behind, so a rewind this large means a new session.
_RESTART_T0_REWIND_US = 2_000_000
_JITTER_EMA_ALPHA = 0.2
# A sync exchange delayed on either side (a scheduling stall, a Wi-Fi retry) has an
# inflated round trip, and its offset estimate is off by up to half of it. Sensors
# apply each offset the server sends, so adopting such an estimate steps their
# t0_us by milliseconds. An exchange whose round trip is well above the one behind
# the current estimate is skipped, unless that estimate is getting old.
_SYNC_RTT_OUTLIER_FACTOR = 2
_SYNC_RTT_OUTLIER_MARGIN_US = 1_000
_SYNC_OUTLIER_MAX_HOLD_US = 8_000_000
# Even an accepted exchange is off by up to half its round trip, and that error
# changes from one exchange to the next (Wi-Fi, scheduling on either side). Once a
# sensor stamps with an offset, a new estimate moves it by at most this much per
# exchange, so its t0_us never steps by more than the raw-capture timeline
# tolerance (0.75 sample, 234 us even at 3200 Hz) and FFT windows across a
# re-sync stay usable. 200 us per 2 s exchange tracks 100 ppm of crystal drift.
_SYNC_MAX_SLEW_US = 200
# An offset that a new exchange proves wrong by more than this (beyond the half
# round trip that exchange can be off) is replaced outright: a few ms of absolute
# error does not matter to analysis, slewing out a large one would take minutes.
_SYNC_STEP_MIN_ERROR_US = 5_000
_SEQ_MASK = 0xFFFFFFFF
_SEQ_HALF = 0x80000000

type ExpectedFrameLoss = Literal["stream_start", "bluetooth_scan", "bluetooth_pairing"]
"""Why a sequence gap is expected rather than a sensor or Wi-Fi fault.

- ``stream_start``: the sensor sends stop-and-wait and drops a frame it could
  not deliver within 0.75 s (``kDataMaxFrameAgeMs``). Frames it queued while the
  server was down (a restart or update) or before its handshake age out while
  the first ones are acknowledged, so its first seconds at this server show a
  gap of a few frames.
- ``bluetooth_scan`` / ``bluetooth_pairing``: the Pi 3's Wi-Fi and Bluetooth
  share one radio; a Bluetooth scan or pairing starves Wi-Fi for its duration.
"""

STREAM_START_GRACE_S = 5.0
"""Gaps this soon after a sensor's stream started are its backlog draining."""
EXPECTED_LOSS_DRAIN_S = 3.0
"""An interruption's backlog keeps surfacing as gaps this long after it ends."""


def _resolve_now_wall(now: float | None) -> float:
    """Return wall-clock ``now`` if provided, else ``time.time()``."""

    return time.time() if now is None else now


def _resolve_now_mono(now_mono: float | None) -> float:
    """Return monotonic ``now_mono`` if provided, else ``time.monotonic()``."""

    return time.monotonic() if now_mono is None else now_mono


@dataclass(slots=True)
class DedupWindow:
    """Track a bounded window of recently seen sequence numbers."""

    _seen_seqs: set[int] = field(default_factory=set)
    _seen_seqs_max: int = -1

    def clear(self) -> None:
        """Reset the dedup window to its initial empty state."""

        self._seen_seqs.clear()
        self._seen_seqs_max = -1

    def contains(self, seq: int) -> bool:
        """Return ``True`` when *seq* is still within the dedup window."""

        return seq in self._seen_seqs

    def record(self, seq: int) -> None:
        """Record *seq* and advance the tracked maximum sequence value."""

        self._seen_seqs.add(seq)
        self._seen_seqs_max = max(self._seen_seqs_max, seq)

    def prune(self, window_size: int) -> None:
        """Discard old entries so the dedup window stays bounded."""

        if len(self._seen_seqs) > window_size:
            cutoff = self._seen_seqs_max - window_size + 1
            self._seen_seqs = {seen for seen in self._seen_seqs if seen >= cutoff}

    def track(self, seq: int, *, window_size: int = _DEFAULT_DEDUP_WINDOW_SIZE) -> bool:
        """Return ``True`` for duplicates; otherwise record *seq* and prune."""

        if self.contains(seq):
            return True
        self.record(seq)
        self.prune(window_size)
        return False


@dataclass(slots=True)
class DataUpdateResult:
    """Return value of :func:`apply_data_message_update`."""

    reset_detected: bool = False
    is_duplicate: bool = False
    is_late: bool = False
    # Whether the frame's t0_us is on the server clock: the sensor has applied a
    # synced clock offset and this frame was stamped with it. Frames stamped on
    # the bare device clock (before the first applied sync) are not alignable.
    clock_synced: bool = False


@dataclass(slots=True)
class ClientRecord:
    """Per-client state: last-seen timestamps, dedup helper, hello/firmware metadata."""

    client_id: str
    name: str
    firmware_version: str = ""
    sample_rate_hz: int = 0
    frame_samples: int = 0
    last_seen: float = 0.0
    last_seen_mono: float = 0.0
    location_code: str = ""
    data_addr: tuple[str, int] | None = None
    control_addr: tuple[str, int] | None = None
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0
    server_queue_drops: int = 0
    parse_errors: int = 0
    last_seq: int | None = None
    last_ack_cmd_seq: int | None = None
    last_ack_status: int | None = None
    pending_sync_cmd_seq: int | None = None
    pending_sync_send_us: int | None = None
    pending_sync_applies_offset: bool = False
    # Set once the sensor acknowledged a sync command that carried an offset to
    # apply; from then on its DATA t0_us values are on the server clock.
    clock_offset_applied: bool = False
    # The latest frame stamped on bare device time (before the offset applied).
    device_frame_seq: int | None = None
    device_frame_t0_us: int | None = None
    sync_offset_us: int | None = None
    sync_rtt_us: int | None = None
    last_sync_monotonic_us: int | None = None
    reset_count: int = 0
    last_reset_time: float | None = None
    last_t0_us: int | None = None
    timing_jitter_us_ema: float = 0.0
    timing_drift_us_total: float = 0.0
    timing_guard: SensorTimingGuard = field(default_factory=SensorTimingGuard)
    duplicates_received: int = 0
    dedup_window: DedupWindow = field(default_factory=DedupWindow)
    # Last-minute counts behind the live and health warnings; the totals above
    # never reset and stay for diagnostics.
    recent_frames: RecentCounter = field(default_factory=RecentCounter)
    recent_frames_dropped: RecentCounter = field(default_factory=RecentCounter)
    # Frames lost to an expected interruption (``ExpectedFrameLoss``): part of
    # ``frames_dropped`` but kept out of the recent loss warnings.
    expected_frames_dropped: int = 0
    recent_expected_frames_dropped: RecentCounter = field(default_factory=RecentCounter)
    last_expected_loss_reason: ExpectedFrameLoss | None = None
    # When the sensor's current stream started at this server (its first frame
    # after the server started, the sensor connected, or the sensor rebooted).
    stream_start_mono: float | None = None
    recent_queue_overflow_drops: RecentCounter = field(default_factory=RecentCounter)
    recent_server_queue_drops: RecentCounter = field(default_factory=RecentCounter)
    recent_parse_errors: RecentCounter = field(default_factory=RecentCounter)


@dataclass(slots=True)
class ClientSnapshot:
    """Raw client snapshot assembled from registry runtime state."""

    client_id: str
    name: str
    connected: bool
    location_code: str = ""
    firmware_version: str = ""
    sample_rate_hz: int = 0
    frame_samples: int = 0
    last_seen_age_ms: int | None = None
    frames_total: int = 0
    dropped_frames: int = 0
    frame_loss_recent: bool = False
    latest_metrics: ClientMetrics | None = None
    reset_count: int = 0
    last_reset_time: float | None = None


@dataclass(frozen=True, slots=True)
class ClientLivenessPolicy:
    """Own the live/retained/stale time windows for tracked clients."""

    live_ttl_seconds: float = 10.0
    retention_ttl_seconds: float = 120.0

    def __post_init__(self) -> None:
        live_ttl_seconds = max(1.0, float(self.live_ttl_seconds))
        retention_ttl_seconds = max(live_ttl_seconds, float(self.retention_ttl_seconds))
        object.__setattr__(self, "live_ttl_seconds", live_ttl_seconds)
        object.__setattr__(self, "retention_ttl_seconds", retention_ttl_seconds)

    def is_live(self, record: ClientRecord, mono_now: float) -> bool:
        return bool(
            record.last_seen_mono and (mono_now - record.last_seen_mono) <= self.live_ttl_seconds,
        )

    def is_retained(self, record: ClientRecord, mono_now: float) -> bool:
        return bool(
            record.last_seen_mono
            and (mono_now - record.last_seen_mono) <= self.retention_ttl_seconds,
        )

    def active_client_ids(
        self,
        clients: Mapping[str, ClientRecord],
        mono_now: float,
    ) -> list[str]:
        return [record.client_id for record in clients.values() if self.is_live(record, mono_now)]

    def stale_client_ids(
        self,
        clients: Mapping[str, ClientRecord],
        mono_now: float,
    ) -> list[str]:
        return [
            client_id
            for client_id, record in clients.items()
            if record.last_seen_mono and not self.is_retained(record, mono_now)
        ]


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


def _is_rebooted_session(
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
        and t0_us < last_t0_us - _RESTART_T0_REWIND_US
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


FRAME_LOSS_WARN_RATIO = 0.01
"""Share of a sensor's frames lost in the recent window that raises a warning.

Wi-Fi drops an occasional UDP datagram; a sensor that lost one frame an hour
ago is healthy now.
"""


def recent_frame_loss(record: ClientRecord, now_mono: float) -> bool:
    """Whether *record* lost at least ``FRAME_LOSS_WARN_RATIO`` of its recent frames."""
    dropped = record.recent_frames_dropped.total(now_mono)
    if dropped == 0:
        return False
    received = record.recent_frames.total(now_mono)
    return dropped >= FRAME_LOSS_WARN_RATIO * (dropped + received)


def apply_data_message_update(
    record: ClientRecord,
    *,
    seq: int,
    sample_count: int,
    t0_us: int,
    addr: tuple[str, int],
    now_ts: float,
    mono: float,
    expected_loss: ExpectedFrameLoss | None = None,
) -> DataUpdateResult:
    """Apply one DATA message to an existing client record.

    A sequence gap counts toward ``frames_dropped``; it raises the recent loss
    warnings unless *expected_loss* names an interruption in progress or the
    sensor's stream only just started.
    """

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
        record.timing_guard.reset()

    rebooted = _is_rebooted_session(record, seq=seq, t0_us=t0_us)
    if rebooted:
        # Treat the rewound frame as the first frame of a new session instead of
        # discarding every frame as "late" until the sensor's clock catches up.
        record.reset_count += 1
        record.last_reset_time = now_ts
        record.last_seq = None
        record.last_t0_us = None
        record.timing_jitter_us_ema = 0.0
        record.timing_drift_us_total = 0.0
        record.dedup_window.clear()
        _forget_clock_sync(record)

    continues_device_timeline = _continues_device_timeline(
        record, seq=seq, t0_us=t0_us, sample_count=sample_count
    )
    clock_synced = record.clock_offset_applied and not continues_device_timeline
    starts_device_timeline = record.device_frame_seq is None and not record.clock_offset_applied
    if continues_device_timeline or starts_device_timeline:
        # Only frames on the device timeline extend it: a frame already stamped
        # on the server clock can arrive before the sync acknowledgement does.
        record.device_frame_seq = seq
        record.device_frame_t0_us = t0_us
    if record.dedup_window.track(seq):
        record.duplicates_received += 1
        return DataUpdateResult(is_duplicate=True, clock_synced=clock_synced)
    if _is_late_packet(record, seq=seq, t0_us=t0_us):
        return DataUpdateResult(is_late=True, clock_synced=clock_synced)

    record.frames_total += 1
    record.recent_frames.add(1, mono)
    if record.last_seq is None:
        record.stream_start_mono = mono
    reset_detected = rebooted
    missed_frames = 0
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
            _forget_clock_sync(record)
            record.stream_start_mono = mono
            clock_synced = False
            reset_detected = True
        else:
            expected = (record.last_seq + 1) & _SEQ_MASK
            if seq != expected:
                gap = (seq - expected) & _SEQ_MASK
                if gap < _SEQ_HALF:
                    _count_dropped_frames(record, gap, mono=mono, expected_loss=expected_loss)
                    missed_frames = gap

    if record.last_seq is None or ((seq - record.last_seq) & _SEQ_MASK) < _SEQ_HALF:
        record.last_seq = seq
    record.last_t0_us = t0_us
    if clock_synced:
        record.timing_guard.observe(
            t0_us=t0_us,
            sample_count=sample_count,
            sample_rate_hz=record.sample_rate_hz,
            receive_mono_s=mono,
            missed_frames=missed_frames,
        )
    return DataUpdateResult(reset_detected=reset_detected, clock_synced=clock_synced)


def _count_dropped_frames(
    record: ClientRecord,
    gap: int,
    *,
    mono: float,
    expected_loss: ExpectedFrameLoss | None,
) -> None:
    record.frames_dropped += gap
    stream_start = record.stream_start_mono
    if expected_loss is None and (
        stream_start is not None and mono - stream_start < STREAM_START_GRACE_S
    ):
        expected_loss = "stream_start"
    if expected_loss is None:
        record.recent_frames_dropped.add(gap, mono)
        return
    record.expected_frames_dropped += gap
    record.recent_expected_frames_dropped.add(gap, mono)
    record.last_expected_loss_reason = expected_loss


def _is_sync_rtt_outlier(
    record: ClientRecord,
    *,
    round_trip_us: int,
    server_receive_us: int,
) -> bool:
    """Return whether to keep the current offset instead of this exchange's estimate."""
    accepted_rtt_us = record.sync_rtt_us
    accepted_at_us = record.last_sync_monotonic_us
    if record.sync_offset_us is None or accepted_rtt_us is None or accepted_at_us is None:
        return False
    if server_receive_us - accepted_at_us >= _SYNC_OUTLIER_MAX_HOLD_US:
        return False
    return round_trip_us > max(
        _SYNC_RTT_OUTLIER_FACTOR * accepted_rtt_us,
        accepted_rtt_us + _SYNC_RTT_OUTLIER_MARGIN_US,
    )


def _disciplined_sync_offset(
    record: ClientRecord,
    *,
    estimate_us: int,
    round_trip_us: int,
) -> int:
    """Return the offset to send next, given this exchange's estimate."""
    current_us = record.sync_offset_us
    if current_us is None or not record.clock_offset_applied:
        # Nothing stamps with an offset yet: take the measurement as is.
        return estimate_us
    deviation_us = estimate_us - current_us
    if abs(deviation_us) - (round_trip_us // 2) > _SYNC_STEP_MIN_ERROR_US:
        return estimate_us
    return current_us + max(-_SYNC_MAX_SLEW_US, min(_SYNC_MAX_SLEW_US, deviation_us))


def _forget_clock_sync(record: ClientRecord) -> None:
    """A rebooted sensor restarts its device clock; its old offset no longer applies."""
    record.clock_offset_applied = False
    record.timing_guard.reset()
    record.device_frame_seq = None
    record.device_frame_t0_us = None
    record.sync_offset_us = None
    record.sync_rtt_us = None
    record.pending_sync_cmd_seq = None
    record.pending_sync_send_us = None
    record.pending_sync_applies_offset = False


# The firmware holds back at most 0.75 s of frames (``kDataMaxFrameAgeMs``) while
# it retransmits; frames further on were queued after the offset was applied.
_MAX_HELD_BACK_FRAMES = 8
# A sensor's sample clock runs continuously: a frame on the same device timeline
# lands within this of where it predicts (sync offsets are ms to seconds).
_DEVICE_TIMELINE_MATCH_US = 5_000.0


def _continues_device_timeline(
    record: ClientRecord,
    *,
    seq: int,
    t0_us: int,
    sample_count: int,
) -> bool:
    """Whether a frame continues the sensor's last frame stamped on bare device time.

    The firmware stamps a frame when it queues it and sends the queue
    stop-and-wait, so frames queued just before the sensor applied the clock
    offset can arrive after the sync acknowledgement, still on device time.
    Their t0 continues the device timeline (``frame duration`` per sequence
    step), while frames stamped after the offset was applied are
    ``sync_offset_us`` away from it. With an offset too small to tell, the two
    timelines coincide and the frame counts as synced.
    """
    ref_seq, ref_t0_us = record.device_frame_seq, record.device_frame_t0_us
    offset_us = record.sync_offset_us
    if ref_seq is None or ref_t0_us is None or record.sample_rate_hz <= 0:
        return False
    if offset_us is not None and abs(offset_us) <= _DEVICE_TIMELINE_MATCH_US:
        return False
    frames_after = (seq - ref_seq) & _SEQ_MASK
    if frames_after == 0 or frames_after > _MAX_HELD_BACK_FRAMES:
        return False
    frame_us = (float(sample_count) / float(record.sample_rate_hz)) * 1_000_000.0
    predicted_t0_us = ref_t0_us + frames_after * frame_us
    return abs(t0_us - predicted_t0_us) <= _DEVICE_TIMELINE_MATCH_US


def project_client_snapshots(
    clients: dict[str, ClientRecord],
    metadata: ClientMetadataManager,
    *,
    now_wall: float,
    now_mono: float,
    policy: ClientLivenessPolicy,
    metrics_by_client: dict[str, ClientMetrics] | None = None,
) -> list[ClientSnapshot]:
    """Build transport-facing ``ClientSnapshot`` rows from registry state."""
    snapshots: list[ClientSnapshot] = []
    for client_id in metadata.known_client_ids(clients):
        record = clients.get(client_id)
        if record is None:
            snapshots.append(
                ClientSnapshot(
                    client_id=client_id,
                    name=metadata.default_name_for(client_id),
                    connected=False,
                ),
            )
            continue
        age_ms = int(max(0.0, now_wall - record.last_seen) * 1000) if record.last_seen else None
        connected = policy.is_live(record, now_mono)
        snapshots.append(
            ClientSnapshot(
                client_id=record.client_id,
                name=record.name,
                connected=connected,
                location_code=record.location_code,
                firmware_version=record.firmware_version,
                sample_rate_hz=record.sample_rate_hz,
                frame_samples=record.frame_samples,
                last_seen_age_ms=age_ms,
                frames_total=record.frames_total,
                dropped_frames=record.frames_dropped,
                frame_loss_recent=recent_frame_loss(record, now_mono),
                latest_metrics=(
                    metrics_by_client.get(record.client_id)
                    if metrics_by_client is not None
                    else None
                ),
                reset_count=record.reset_count,
                last_reset_time=record.last_reset_time,
            ),
        )
    return snapshots


class ClientRegistry:
    """Thread-safe registry of live and recently-retained ESP32 clients."""

    def __init__(
        self,
        db: HistoryDB | None = None,
        live_ttl_seconds: float = 10.0,
        retention_ttl_seconds: float = 120.0,
    ):
        self._lock = RLock()
        self._liveness_policy = ClientLivenessPolicy(
            live_ttl_seconds=live_ttl_seconds,
            retention_ttl_seconds=retention_ttl_seconds,
        )
        self._clients: dict[str, ClientRecord] = {}
        self._expected_loss: ExpectedFrameLoss | None = None
        self._expected_loss_until_mono = 0.0
        self._metadata = ClientMetadataManager(
            lock=self._lock,
            get_or_create=self._get_or_create,
            list_client_names=db.list_client_names if db is not None else None,
            persist_client_name=db.upsert_client_name if db is not None else None,
            delete_client_name=db.delete_client_name if db is not None else None,
        )

    @staticmethod
    def _normalize_wire_client_id(client_id: bytes) -> str:
        return normalize_sensor_id(client_id.hex())

    def _get_or_create(self, client_id: str) -> ClientRecord:
        normalized = normalize_sensor_id(client_id)
        record = self._clients.get(normalized)
        if record is None:
            default_name = self._metadata.default_name_for(normalized)
            record = ClientRecord(client_id=normalized, name=default_name)
            self._clients[normalized] = record
        return record

    def update_from_hello(
        self,
        hello: HelloMessage,
        addr: tuple[str, int],
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> bool:
        """Record a HELLO; return whether the sensor needs a clock-sync exchange now.

        A sensor that is not stamping on the server clock yet (it just connected or
        rebooted) and has no exchange in flight is synced right away instead of at
        the next periodic broadcast, so it streams few chunks raw capture must drop.
        """
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = self._normalize_wire_client_id(hello.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = mono
            hello_port = int(hello.control_port)
            record.control_addr = (addr[0], hello_port if hello_port > 0 else addr[1])
            record.sample_rate_hz = hello.sample_rate_hz
            record.frame_samples = hello.frame_samples
            if record.firmware_version and hello.firmware_version != record.firmware_version:
                record.reset_count += 1
                record.last_reset_time = now_ts
                record.dedup_window.clear()
            record.firmware_version = hello.firmware_version
            reported = hello.queue_overflow_drops
            # The device counter restarts from zero when the sensor reboots.
            new_drops = (
                reported
                if reported < record.queue_overflow_drops
                else (reported - record.queue_overflow_drops)
            )
            record.recent_queue_overflow_drops.add(new_drops, mono)
            record.queue_overflow_drops = reported
            self._metadata.apply_advertised_name(record, hello.name)
            return not record.clock_offset_applied and record.pending_sync_cmd_seq is None

    def update_from_data(
        self,
        data_msg: DataMessage,
        addr: tuple[str, int],
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> DataUpdateResult:
        """Update bookkeeping from a DATA message.

        Returns a :class:`DataUpdateResult` indicating whether a sensor reset
        was detected and whether this message is a duplicate retransmit.
        Duplicates are tracked but do not inflate counters or timing metrics.
        """
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = self._normalize_wire_client_id(data_msg.client_id)
            record = self._get_or_create(client_id)
            return apply_data_message_update(
                record,
                seq=data_msg.seq,
                sample_count=data_msg.sample_count,
                t0_us=data_msg.t0_us,
                addr=addr,
                now_ts=now_ts,
                mono=mono,
                expected_loss=(
                    self._expected_loss if mono <= self._expected_loss_until_mono else None
                ),
            )

    @contextmanager
    def expecting_frame_loss(self, reason: ExpectedFrameLoss) -> Iterator[None]:
        """Attribute sequence gaps to *reason* while the block runs and briefly after."""
        with self._lock:
            self._expected_loss = reason
            self._expected_loss_until_mono = math.inf
        try:
            yield
        finally:
            with self._lock:
                self._expected_loss_until_mono = time.monotonic() + EXPECTED_LOSS_DRAIN_S

    def update_from_ack(
        self,
        ack: AckMessage,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> bool:
        """Record an ACK; return whether a measured offset now awaits its applying exchange.

        The first exchange with a sensor only measures the offset; sending the
        exchange that carries it at once, rather than at the next broadcast, puts
        the sensor on the server clock within two round trips of connecting.
        """
        with self._lock:
            now_ts = _resolve_now_wall(now)
            mono = _resolve_now_mono(now_mono)
            client_id = self._normalize_wire_client_id(ack.client_id)
            record = self._get_or_create(client_id)
            record.last_seen = now_ts
            record.last_seen_mono = mono
            record.last_ack_cmd_seq = ack.cmd_seq
            record.last_ack_status = ack.status
            if record.pending_sync_cmd_seq != ack.cmd_seq:
                return False
            if record.pending_sync_applies_offset:
                record.clock_offset_applied = True
            if (
                ack.device_receive_us is not None
                and ack.device_send_us is not None
                and record.pending_sync_send_us is not None
            ):
                server_receive_us = int(mono * 1_000_000)
                processing_us = max(0, ack.device_send_us - ack.device_receive_us)
                round_trip_us = max(
                    0,
                    server_receive_us - record.pending_sync_send_us - processing_us,
                )
                if not _is_sync_rtt_outlier(
                    record,
                    round_trip_us=round_trip_us,
                    server_receive_us=server_receive_us,
                ):
                    record.sync_offset_us = _disciplined_sync_offset(
                        record,
                        estimate_us=(
                            (record.pending_sync_send_us - ack.device_receive_us)
                            + (server_receive_us - ack.device_send_us)
                        )
                        // 2,
                        round_trip_us=round_trip_us,
                    )
                    record.sync_rtt_us = round_trip_us
                    record.last_sync_monotonic_us = server_receive_us
            record.pending_sync_cmd_seq = None
            record.pending_sync_send_us = None
            record.pending_sync_applies_offset = False
            return not record.clock_offset_applied and record.sync_offset_us is not None

    def _note_client_counter(
        self,
        client_id: str | None,
        attr: Literal["parse_errors", "server_queue_drops"],
    ) -> None:
        if not client_id:
            return
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return
        with self._lock:
            record = self._get_or_create(normalized)
            setattr(record, attr, getattr(record, attr) + 1)
            recent: RecentCounter = getattr(record, f"recent_{attr}")
            recent.add(1, _resolve_now_mono(None))

    def note_parse_error(self, client_id: str | None) -> None:
        self._note_client_counter(client_id, "parse_errors")

    def note_server_queue_drop(self, client_id: str | None) -> None:
        self._note_client_counter(client_id, "server_queue_drops")

    def set_name(self, client_id: str, name: str) -> ClientRecord:
        return self._metadata.set_name(client_id, name)

    def clear_name(self, client_id: str) -> ClientRecord:
        """Remove the user-assigned name and revert to the default."""
        return self._metadata.clear_name(client_id)

    def set_location(self, client_id: str, location: str) -> ClientRecord:
        """Assign a location code (e.g. ``"front-left"``) to a sensor.

        The value is stripped of leading/trailing whitespace and capped at
        64 UTF-8 bytes to bound stored string size (consistent with the
        32-byte cap applied to client names).

        Raises
        ------
        ValueError
            If the location is already assigned to a different client.
        """
        normalized_client_id = normalize_sensor_id(client_id)
        clean = _LOCATION_VALIDATOR.normalize(location)
        with self._lock:
            _LOCATION_VALIDATOR.validate_assignment(
                owner_id=normalized_client_id,
                location_code=clean,
                assigned_locations=(
                    AssignedLocation(
                        owner_id=cid,
                        owner_name=rec.name or cid,
                        location_code=rec.location_code,
                    )
                    for cid, rec in self._clients.items()
                ),
            )
            record = self._get_or_create(normalized_client_id)
            record.location_code = clean
            return record

    def remove_client(self, client_id: str) -> bool:
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return False
        with self._lock:
            had_client = normalized in self._clients
            self._clients.pop(normalized, None)
        had_name = self._metadata.discard_name(normalized)
        return had_client or had_name

    def get(self, client_id: str) -> ClientRecord | None:
        """Return a point-in-time copy of *client_id*'s record."""
        try:
            normalized = normalize_sensor_id(client_id)
        except ValueError:
            return None
        with self._lock:
            record = self._clients.get(normalized)
            if record is None:
                return None
            return copy.copy(record)

    def active_client_ids(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
    ) -> list[str]:
        with self._lock:
            mono_now = _resolve_now_mono(now_mono)
            return self._liveness_policy.active_client_ids(self._clients, mono_now)

    def recent_data_loss_snapshot(self, *, now_mono: float | None = None) -> dict[str, int]:
        """Data loss in the last ``RECENT_WINDOW_S`` seconds, summed over clients.

        ``frame_loss_clients`` counts clients over ``FRAME_LOSS_WARN_RATIO``.
        ``expected_frames_dropped`` (an expected interruption) is not in
        ``frames_dropped``.
        """
        with self._lock:
            mono = _resolve_now_mono(now_mono)
            snapshot: dict[str, int] = {
                "window_s": int(RECENT_WINDOW_S),
                "frame_loss_clients": 0,
                "frames_dropped": 0,
                "expected_frames_dropped": 0,
                "queue_overflow_drops": 0,
                "server_queue_drops": 0,
                "parse_errors": 0,
            }
            for record in self._clients.values():
                if recent_frame_loss(record, mono):
                    snapshot["frame_loss_clients"] += 1
                snapshot["frames_dropped"] += record.recent_frames_dropped.total(mono)
                snapshot["expected_frames_dropped"] += record.recent_expected_frames_dropped.total(
                    mono
                )
                snapshot["queue_overflow_drops"] += record.recent_queue_overflow_drops.total(mono)
                snapshot["server_queue_drops"] += record.recent_server_queue_drops.total(mono)
                snapshot["parse_errors"] += record.recent_parse_errors.total(mono)
            return snapshot

    def data_loss_snapshot(self) -> dict[str, int]:
        with self._lock:
            snapshot: dict[str, int] = {
                "tracked_clients": len(self._clients),
                "affected_clients": 0,
                "frames_dropped": 0,
                "queue_overflow_drops": 0,
                "server_queue_drops": 0,
                "parse_errors": 0,
            }
            for record in self._clients.values():
                snapshot["frames_dropped"] += int(record.frames_dropped)
                snapshot["queue_overflow_drops"] += int(record.queue_overflow_drops)
                snapshot["server_queue_drops"] += int(record.server_queue_drops)
                snapshot["parse_errors"] += int(record.parse_errors)
                if (
                    record.frames_dropped > 0
                    or record.queue_overflow_drops > 0
                    or record.server_queue_drops > 0
                    or record.parse_errors > 0
                ):
                    snapshot["affected_clients"] += 1
            return snapshot

    def evict_stale(self, now: float | None = None, *, now_mono: float | None = None) -> list[str]:
        with self._lock:
            mono_now = _resolve_now_mono(now_mono)
            stale_ids = self._liveness_policy.stale_client_ids(self._clients, mono_now)
            for client_id in stale_ids:
                self._clients.pop(client_id, None)
            return stale_ids

    def mark_cmd_sent(
        self,
        client_id: str,
        cmd_seq: int,
        *,
        sync_send_us: int | None = None,
        sync_applies_offset: bool = False,
    ) -> None:
        with self._lock:
            record = self._get_or_create(client_id)
            record.last_ack_cmd_seq = cmd_seq
            record.last_ack_status = None
            if sync_send_us is not None:
                record.pending_sync_cmd_seq = cmd_seq
                record.pending_sync_send_us = sync_send_us
                record.pending_sync_applies_offset = sync_applies_offset

    def client_snapshots(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
        metrics_by_client: dict[str, ClientMetrics] | None = None,
    ) -> list[ClientSnapshot]:
        """Return raw per-client snapshots for transport presenters."""
        with self._lock:
            return project_client_snapshots(
                self._clients,
                self._metadata,
                now_wall=_resolve_now_wall(now),
                now_mono=_resolve_now_mono(now_mono),
                policy=self._liveness_policy,
                metrics_by_client=metrics_by_client,
            )
