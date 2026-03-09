"""UDP data receiver — ingests binary sensor payloads from ESP32 nodes.

``UDPDataRxProtocol`` is an asyncio ``DatagramProtocol`` that decodes
incoming ``DataMessage`` frames, deduplicates them via the client registry,
runs the processing pipeline, and hands results to the metrics logger.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import cast

from .processing import SignalProcessor
from .protocol import MSG_DATA, extract_client_id_hex, pack_data_ack, parse_data
from .registry import ClientRegistry

LOGGER = logging.getLogger(__name__)

_QUEUE_DROP_LOG_INTERVAL_S: float = 2.0


class DataDatagramProtocol(asyncio.DatagramProtocol):
    """asyncio ``DatagramProtocol`` that ingests UDP sensor data frames."""

    _MSG_DATA: int = MSG_DATA  # class-level cache avoids module-dict lookup per packet

    def __init__(
        self,
        registry: ClientRegistry,
        processor: SignalProcessor,
        queue_maxsize: int = 1024,
        queue_drop_log_interval_s: float = _QUEUE_DROP_LOG_INTERVAL_S,
    ):
        self.registry = registry
        self.processor = processor
        self.transport: asyncio.DatagramTransport | None = None
        self._queue: asyncio.Queue[tuple[bytes, tuple[str, int]]] = asyncio.Queue(
            maxsize=max(1, queue_maxsize)
        )
        self._queue_drop_log_interval_s = max(0.0, float(queue_drop_log_interval_s))
        self._last_queue_drop_log_ts = 0.0
        self._suppressed_queue_drop_warnings = 0

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Store the transport reference when the datagram endpoint is established."""
        self.transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Enqueue an incoming datagram for background processing."""
        if not data:
            return
        if data[0] != self._MSG_DATA:
            return
        try:
            self._queue.put_nowait((data, addr))
        except asyncio.QueueFull:
            client_id = extract_client_id_hex(data)
            self.registry.note_server_queue_drop(client_id)
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
            data, addr = await self._queue.get()
            try:
                self._process_datagram(data, addr)
            except (ValueError, KeyError, OSError):
                LOGGER.warning(
                    "Unexpected error processing UDP datagram from %s; "
                    "dropping packet to keep consumer alive.",
                    addr,
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    def _process_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            msg = parse_data(data)
        except Exception as exc:
            client_id = extract_client_id_hex(data)
            LOGGER.debug("DATA parse error from %s (client=%s): %s", addr, client_id, exc)
            self.registry.note_parse_error(client_id)
            return

        client_id = msg.client_id.hex()
        registry = self.registry
        processor = self.processor
        try:
            now_ts = time.time()
            result = registry.update_from_data(msg, addr, now_ts)
            if not result.is_duplicate:
                if result.reset_detected:
                    LOGGER.warning(
                        "Sensor reset detected for %s — flushing FFT buffer",
                        client_id,
                    )
                    processor.flush_client_buffer(client_id)
                record = registry.get(client_id)
                sample_rate_hz = record.sample_rate_hz if record is not None else None
                processor.ingest(
                    client_id, msg.samples, sample_rate_hz=sample_rate_hz, t0_us=msg.t0_us
                )
            transport = self.transport
            if transport is not None:
                ack_payload = pack_data_ack(msg.client_id, msg.seq)
                transport.sendto(ack_payload, addr)
        except (ValueError, KeyError, OSError):
            LOGGER.warning(
                "Error processing datagram from %s (client=%s)",
                addr,
                client_id,
                exc_info=True,
            )


async def start_udp_data_receiver(
    host: str,
    port: int,
    registry: ClientRegistry,
    processor: SignalProcessor,
    queue_maxsize: int = 1024,
) -> tuple[asyncio.DatagramTransport, asyncio.Task[None]]:
    """Bind the UDP data socket and start the background consumer task."""
    loop = asyncio.get_running_loop()
    protocol = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        queue_maxsize=queue_maxsize,
    )
    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol,
        local_addr=(host, port),
    )
    consumer = asyncio.create_task(protocol.process_queue(), name="udp-data-consumer")
    return transport, consumer
