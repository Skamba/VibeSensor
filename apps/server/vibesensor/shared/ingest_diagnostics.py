from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Literal

__all__ = [
    "ClientIngestRuntimeSnapshot",
    "IngestDiagnosticsCollector",
    "RawCaptureRuntimeSnapshot",
    "UdpIngestRuntimeSnapshot",
    "WsPublishRuntimeSnapshot",
]

type RawCapturePressureState = Literal["ok", "warn", "degraded"]


def _ms(value_s: float) -> float:
    return round(max(0.0, float(value_s)) * 1000.0, 3)


@dataclass(frozen=True, slots=True)
class ClientIngestRuntimeSnapshot:
    processed_packets: int = 0
    processed_samples: int = 0
    estimated_ingest_hz: float = 0.0
    late_packets: int = 0
    last_packet_queue_age_ms: float = 0.0
    last_ack_latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class UdpIngestRuntimeSnapshot:
    queue_depth: int = 0
    queue_max_depth: int = 0
    enqueued_datagrams: int = 0
    dropped_datagrams: int = 0
    processed_datagrams: int = 0
    last_packet_queue_age_ms: float = 0.0
    max_packet_queue_age_ms: float = 0.0
    last_ack_latency_ms: float = 0.0
    max_ack_latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class RawCaptureRuntimeSnapshot:
    queue_depth: int = 0
    queue_max_depth: int = 0
    dropped_chunks: int = 0
    write_error_chunks: int = 0
    pressure_state: RawCapturePressureState = "ok"


@dataclass(frozen=True, slots=True)
class WsPublishRuntimeSnapshot:
    active_connections: int = 0
    total_publish_ticks: int = 0
    last_publish_duration_ms: float = 0.0
    max_publish_duration_ms: float = 0.0


@dataclass(slots=True)
class _ClientState:
    processed_packets: int = 0
    processed_samples: int = 0
    estimated_ingest_hz: float = 0.0
    late_packets: int = 0
    last_packet_queue_age_s: float = 0.0
    last_ack_latency_s: float = 0.0
    last_processed_mono_s: float | None = None


class IngestDiagnosticsCollector:
    """Own cross-cutting live ingest diagnostics across UDP, raw capture, and WS publish."""

    __slots__ = (
        "_clients",
        "_lock",
        "_raw_capture_current_depth",
        "_raw_capture_dropped_chunks",
        "_raw_capture_max_depth",
        "_raw_capture_write_error_chunks",
        "_udp_current_depth",
        "_udp_dropped_datagrams",
        "_udp_enqueued_datagrams",
        "_udp_last_ack_latency_s",
        "_udp_last_packet_queue_age_s",
        "_udp_max_depth",
        "_udp_max_ack_latency_s",
        "_udp_max_packet_queue_age_s",
        "_udp_processed_datagrams",
        "_ws_active_connections",
        "_ws_last_publish_duration_s",
        "_ws_max_publish_duration_s",
        "_ws_total_publish_ticks",
    )

    def __init__(self) -> None:
        self._lock = RLock()
        self._clients: dict[str, _ClientState] = {}
        self._udp_current_depth = 0
        self._udp_max_depth = 0
        self._udp_enqueued_datagrams = 0
        self._udp_dropped_datagrams = 0
        self._udp_processed_datagrams = 0
        self._udp_last_packet_queue_age_s = 0.0
        self._udp_max_packet_queue_age_s = 0.0
        self._udp_last_ack_latency_s = 0.0
        self._udp_max_ack_latency_s = 0.0
        self._raw_capture_current_depth = 0
        self._raw_capture_max_depth = 0
        self._raw_capture_dropped_chunks = 0
        self._raw_capture_write_error_chunks = 0
        self._ws_active_connections = 0
        self._ws_total_publish_ticks = 0
        self._ws_last_publish_duration_s = 0.0
        self._ws_max_publish_duration_s = 0.0

    def _client(self, client_id: str) -> _ClientState:
        return self._clients.setdefault(client_id, _ClientState())

    def note_udp_queue_depth(self, depth: int) -> None:
        with self._lock:
            self._udp_current_depth = max(0, int(depth))
            self._udp_max_depth = max(self._udp_max_depth, self._udp_current_depth)

    def note_udp_enqueued(self, depth: int) -> None:
        with self._lock:
            self._udp_enqueued_datagrams += 1
            self._udp_current_depth = max(0, int(depth))
            self._udp_max_depth = max(self._udp_max_depth, self._udp_current_depth)

    def note_udp_drop(self, depth: int) -> None:
        with self._lock:
            self._udp_dropped_datagrams += 1
            self._udp_current_depth = max(0, int(depth))
            self._udp_max_depth = max(self._udp_max_depth, self._udp_current_depth)

    def note_udp_processed(
        self,
        *,
        client_id: str,
        sample_count: int,
        queue_age_s: float,
        ack_latency_s: float,
        processed_at_mono_s: float,
        count_for_ingest: bool,
    ) -> None:
        with self._lock:
            self._udp_processed_datagrams += 1
            self._udp_last_packet_queue_age_s = max(0.0, float(queue_age_s))
            self._udp_max_packet_queue_age_s = max(
                self._udp_max_packet_queue_age_s,
                self._udp_last_packet_queue_age_s,
            )
            self._udp_last_ack_latency_s = max(0.0, float(ack_latency_s))
            self._udp_max_ack_latency_s = max(
                self._udp_max_ack_latency_s,
                self._udp_last_ack_latency_s,
            )
            client = self._client(client_id)
            client.last_packet_queue_age_s = self._udp_last_packet_queue_age_s
            client.last_ack_latency_s = self._udp_last_ack_latency_s
            if count_for_ingest:
                if (
                    client.last_processed_mono_s is not None
                    and processed_at_mono_s > client.last_processed_mono_s
                    and sample_count > 0
                ):
                    elapsed_s = processed_at_mono_s - client.last_processed_mono_s
                    client.estimated_ingest_hz = float(sample_count) / elapsed_s
                client.last_processed_mono_s = processed_at_mono_s
                client.processed_packets += 1
                client.processed_samples += max(0, int(sample_count))

    def note_late_packet(self, *, client_id: str) -> None:
        with self._lock:
            self._client(client_id).late_packets += 1

    def note_raw_capture_queue_depth(self, depth: int) -> None:
        with self._lock:
            self._raw_capture_current_depth = max(0, int(depth))
            self._raw_capture_max_depth = max(
                self._raw_capture_max_depth,
                self._raw_capture_current_depth,
            )

    def note_raw_capture_drop(self, *, depth: int) -> None:
        with self._lock:
            self._raw_capture_dropped_chunks += 1
            self._raw_capture_current_depth = max(0, int(depth))
            self._raw_capture_max_depth = max(
                self._raw_capture_max_depth,
                self._raw_capture_current_depth,
            )

    def note_raw_capture_write_error(self) -> None:
        with self._lock:
            self._raw_capture_write_error_chunks += 1

    def note_ws_publish(self, *, connection_count: int, duration_s: float) -> None:
        with self._lock:
            self._ws_active_connections = max(0, int(connection_count))
            self._ws_total_publish_ticks += 1
            self._ws_last_publish_duration_s = max(0.0, float(duration_s))
            self._ws_max_publish_duration_s = max(
                self._ws_max_publish_duration_s,
                self._ws_last_publish_duration_s,
            )

    def udp_snapshot(self) -> UdpIngestRuntimeSnapshot:
        with self._lock:
            return UdpIngestRuntimeSnapshot(
                queue_depth=self._udp_current_depth,
                queue_max_depth=self._udp_max_depth,
                enqueued_datagrams=self._udp_enqueued_datagrams,
                dropped_datagrams=self._udp_dropped_datagrams,
                processed_datagrams=self._udp_processed_datagrams,
                last_packet_queue_age_ms=_ms(self._udp_last_packet_queue_age_s),
                max_packet_queue_age_ms=_ms(self._udp_max_packet_queue_age_s),
                last_ack_latency_ms=_ms(self._udp_last_ack_latency_s),
                max_ack_latency_ms=_ms(self._udp_max_ack_latency_s),
            )

    def raw_capture_snapshot(self) -> RawCaptureRuntimeSnapshot:
        with self._lock:
            return RawCaptureRuntimeSnapshot(
                queue_depth=self._raw_capture_current_depth,
                queue_max_depth=self._raw_capture_max_depth,
                dropped_chunks=self._raw_capture_dropped_chunks,
                write_error_chunks=self._raw_capture_write_error_chunks,
                pressure_state=_raw_capture_pressure_state(
                    queue_depth=self._raw_capture_current_depth,
                    queue_max_depth=self._raw_capture_max_depth,
                    dropped_chunks=self._raw_capture_dropped_chunks,
                    write_error_chunks=self._raw_capture_write_error_chunks,
                ),
            )

    def ws_publish_snapshot(self) -> WsPublishRuntimeSnapshot:
        with self._lock:
            return WsPublishRuntimeSnapshot(
                active_connections=self._ws_active_connections,
                total_publish_ticks=self._ws_total_publish_ticks,
                last_publish_duration_ms=_ms(self._ws_last_publish_duration_s),
                max_publish_duration_ms=_ms(self._ws_max_publish_duration_s),
            )

    def client_snapshots(self) -> dict[str, ClientIngestRuntimeSnapshot]:
        with self._lock:
            return {
                client_id: ClientIngestRuntimeSnapshot(
                    processed_packets=state.processed_packets,
                    processed_samples=state.processed_samples,
                    estimated_ingest_hz=round(state.estimated_ingest_hz, 3),
                    late_packets=state.late_packets,
                    last_packet_queue_age_ms=_ms(state.last_packet_queue_age_s),
                    last_ack_latency_ms=_ms(state.last_ack_latency_s),
                )
                for client_id, state in self._clients.items()
            }


def _raw_capture_pressure_state(
    *,
    queue_depth: int,
    queue_max_depth: int,
    dropped_chunks: int,
    write_error_chunks: int,
) -> RawCapturePressureState:
    if write_error_chunks > 0 or dropped_chunks >= 10:
        return "degraded"
    if dropped_chunks > 0 or queue_depth > 0 or queue_max_depth >= 1024:
        return "warn"
    return "ok"
