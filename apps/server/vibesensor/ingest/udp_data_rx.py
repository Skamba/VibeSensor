"""UDP data receiver — ingests binary sensor payloads from ESP32 nodes.

``UDPDataRxProtocol`` is an asyncio ``DatagramProtocol`` that decodes
incoming ``DataMessage`` frames, deduplicates them via the client registry,
runs the processing pipeline, and hands results to the metrics logger.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from vibesensor.common.exceptions import ProtocolError
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.protocol_messages import DataMessage, extract_client_id_hex
from vibesensor.ingest.protocol_packing import pack_data_ack
from vibesensor.ingest.protocol_parsing import parse_data
from vibesensor.ingest.protocol_validator import ProtocolVersionMismatch
from vibesensor.ingest.protocol_wire import MSG_DATA
from vibesensor.ingest.registry import ClientRegistry, DataUpdateResult
from vibesensor.live.processor import SignalProcessor

if TYPE_CHECKING:
    from vibesensor.recording.raw_capture_writer import RunRawCaptureWriter

LOGGER = logging.getLogger(__name__)

_QUEUE_DROP_LOG_INTERVAL_S: float = 2.0


class DatagramDispatchError(RuntimeError):
    """Operational failure while dispatching one parsed DATA message."""

    def __init__(
        self,
        *,
        client_id: str,
        addr: tuple[str, int],
        detail: str,
    ) -> None:
        super().__init__(detail)
        self.client_id = client_id
        self.addr = addr


class DataDatagramProtocol(asyncio.DatagramProtocol):
    """asyncio ``DatagramProtocol`` that ingests UDP sensor data frames."""

    _MSG_DATA: int = MSG_DATA  # class-level cache avoids module-dict lookup per packet

    def __init__(
        self,
        registry: ClientRegistry,
        processor: SignalProcessor,
        raw_capture_sink: RunRawCaptureWriter | None = None,
        ingest_diagnostics: IngestDiagnosticsCollector | None = None,
        queue_maxsize: int = 1024,
        queue_drop_log_interval_s: float = _QUEUE_DROP_LOG_INTERVAL_S,
        sync_clock_now: Callable[[str], object] | None = None,
    ):
        self.registry = registry
        self.processor = processor
        self._raw_capture_sink = raw_capture_sink
        # Starts a clock-sync exchange with one sensor (``UDPControlPlane.send_sync_clock``).
        self._sync_clock_now = sync_clock_now
        self._ingest_diagnostics = ingest_diagnostics
        self.transport: asyncio.DatagramTransport | None = None
        self._queue: asyncio.Queue[tuple[bytes, tuple[str, int], float]] = asyncio.Queue(
            maxsize=max(1, queue_maxsize),
        )
        self._queue_drop_log_interval_s = max(0.0, float(queue_drop_log_interval_s))
        self._last_queue_drop_log_ts = 0.0
        self._suppressed_queue_drop_warnings = 0

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the transport reference when the datagram endpoint is established."""
        self.transport = cast("asyncio.DatagramTransport", transport)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Enqueue an incoming datagram for background processing."""
        if not data:
            return
        if data[0] != self._MSG_DATA:
            return
        received_mono_s = time.monotonic()
        try:
            self._queue.put_nowait((data, addr, received_mono_s))
            if self._ingest_diagnostics is not None:
                self._ingest_diagnostics.note_udp_enqueued(self._queue.qsize())
        except asyncio.QueueFull:
            client_id = extract_client_id_hex(data)
            self.registry.note_server_queue_drop(client_id)
            if self._ingest_diagnostics is not None:
                self._ingest_diagnostics.note_udp_drop(self._queue.qsize())
            now = time.monotonic()
            if (now - self._last_queue_drop_log_ts) >= self._queue_drop_log_interval_s:
                suppressed = self._suppressed_queue_drop_warnings
                self._suppressed_queue_drop_warnings = 0
                self._last_queue_drop_log_ts = now
                if suppressed > 0:
                    LOGGER.warning(
                        "UDP ingest queue full; dropping packet from %s (client=%s); "
                        "suppressed %d additional drop warnings",
                        addr,
                        client_id,
                        suppressed,
                    )
                else:
                    LOGGER.warning(
                        "UDP ingest queue full; dropping packet from %s (client=%s)",
                        addr,
                        client_id,
                    )
            else:
                self._suppressed_queue_drop_warnings += 1
            return

    async def process_queue(self) -> None:
        """Consume the ingestion queue until cancelled, processing each datagram."""
        while True:
            data, addr, received_mono_s = await self._queue.get()
            try:
                if self._ingest_diagnostics is not None:
                    self._ingest_diagnostics.note_udp_queue_depth(self._queue.qsize())
                self._process_datagram(data, addr, received_mono_s=received_mono_s)
            except DatagramDispatchError as exc:
                LOGGER.warning(
                    "Error processing datagram from %s (client=%s): %s",
                    exc.addr,
                    exc.client_id,
                    exc,
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    def _process_datagram(
        self,
        data: bytes,
        addr: tuple[str, int],
        *,
        received_mono_s: float | None = None,
    ) -> None:
        msg = self._parse_data_message(data, addr)
        if msg is None:
            return
        self._dispatch_data_message(msg, addr, received_mono_s=received_mono_s)

    def _parse_data_message(self, data: bytes, addr: tuple[str, int]) -> DataMessage | None:
        try:
            return parse_data(data)
        except ProtocolVersionMismatch as exc:
            client_id = extract_client_id_hex(data)
            LOGGER.warning("DATA version mismatch from %s (client=%s): %s", addr, client_id, exc)
            self.registry.note_parse_error(client_id)
            return None
        except ProtocolError as exc:
            client_id = extract_client_id_hex(data)
            LOGGER.debug("DATA parse error from %s (client=%s): %s", addr, client_id, exc)
            self.registry.note_parse_error(client_id)
            return None

    def _dispatch_data_message(
        self,
        msg: DataMessage,
        addr: tuple[str, int],
        *,
        received_mono_s: float | None = None,
    ) -> DataUpdateResult:
        client_id = msg.client_id.hex()
        registry = self.registry
        processor = self.processor
        dispatch_started_mono_s = time.monotonic()
        queue_age_s = (
            max(0.0, dispatch_started_mono_s - received_mono_s)
            if received_mono_s is not None
            else 0.0
        )
        now_ts = time.time()
        result = registry.update_from_data(msg, addr, now_ts)
        if result.sync_due and self._sync_clock_now is not None:
            self._sync_clock_now(client_id)
        if not result.is_duplicate:
            if result.reset_detected:
                LOGGER.warning(
                    "Sensor reset detected for %s — flushing FFT buffer",
                    client_id,
                )
                processor.flush_client_buffer(client_id)
            record = registry.get(client_id)
            sample_rate_hz = record.sample_rate_hz if record is not None else None
            if not result.is_late:
                processor.ingest(
                    client_id,
                    msg.samples,
                    sample_rate_hz=sample_rate_hz,
                    # Before clock sync, t0 is the sensor's own uptime, not server time.
                    t0_us=msg.t0_us if result.clock_synced else None,
                )
            if self._raw_capture_sink is not None:
                if result.is_late:
                    self._raw_capture_sink.note_late_packet_loss(client_id=client_id)
                if result.clock_synced:
                    self._raw_capture_sink.capture_raw_samples(
                        client_id=client_id,
                        sample_rate_hz=sample_rate_hz,
                        t0_us=msg.t0_us,
                        samples=msg.samples,
                    )
                else:
                    # Raw capture is aligned on the server clock, so a sensor's
                    # chunks start at its first frame stamped after clock sync.
                    self._raw_capture_sink.note_presync_chunk(client_id=client_id)
        if result.is_late and self._ingest_diagnostics is not None:
            self._ingest_diagnostics.note_late_packet(client_id=client_id)
        self._send_data_ack(msg, addr, client_id=client_id)
        if self._ingest_diagnostics is not None:
            ack_completed_mono_s = time.monotonic()
            self._ingest_diagnostics.note_udp_processed(
                client_id=client_id,
                sample_count=len(msg.samples),
                queue_age_s=queue_age_s,
                ack_latency_s=max(
                    0.0,
                    ack_completed_mono_s - (received_mono_s or dispatch_started_mono_s),
                ),
                processed_at_mono_s=ack_completed_mono_s,
                count_for_ingest=not result.is_duplicate and not result.is_late,
            )
        return result

    def _send_data_ack(
        self,
        msg: DataMessage,
        addr: tuple[str, int],
        *,
        client_id: str,
    ) -> None:
        transport = self.transport
        if transport is None:
            return
        ack_payload = pack_data_ack(msg.client_id, msg.seq)
        try:
            transport.sendto(ack_payload, addr)
        except OSError as exc:
            raise DatagramDispatchError(
                client_id=client_id,
                addr=addr,
                detail="failed to send DATA_ACK",
            ) from exc


async def start_udp_data_receiver(
    host: str,
    port: int,
    registry: ClientRegistry,
    processor: SignalProcessor,
    raw_capture_sink: RunRawCaptureWriter | None = None,
    ingest_diagnostics: IngestDiagnosticsCollector | None = None,
    queue_maxsize: int = 1024,
    sync_clock_now: Callable[[str], object] | None = None,
) -> tuple[asyncio.DatagramTransport, DataDatagramProtocol]:
    """Bind the UDP data socket and start the background consumer task."""
    loop = asyncio.get_running_loop()
    protocol = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        raw_capture_sink=raw_capture_sink,
        ingest_diagnostics=ingest_diagnostics,
        queue_maxsize=queue_maxsize,
        sync_clock_now=sync_clock_now,
    )
    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol,
        local_addr=(host, port),
    )
    return transport, protocol
