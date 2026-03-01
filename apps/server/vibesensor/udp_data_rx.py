from __future__ import annotations

import asyncio
import logging
import time

from .processing import SignalProcessor
from .protocol import MSG_DATA, ProtocolError, extract_client_id_hex, pack_data_ack, parse_data
from .registry import ClientRegistry

LOGGER = logging.getLogger(__name__)

_QUEUE_DROP_LOG_INTERVAL_S: float = 10.0


class DataDatagramProtocol(asyncio.DatagramProtocol):
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
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data:
            return
        if data[0] != MSG_DATA:
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
        while True:
            data, addr = await self._queue.get()
            try:
                self._process_datagram(data, addr)
            finally:
                self._queue.task_done()

    def _process_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            msg = parse_data(data)
        except ProtocolError as exc:
            client_id = extract_client_id_hex(data)
            LOGGER.debug("DATA parse error from %s (client=%s): %s", addr, client_id, exc)
            self.registry.note_parse_error(client_id)
            return

        client_id = msg.client_id.hex()
        try:
            now_ts = time.time()
            result = self.registry.update_from_data(msg, addr, now_ts)
            if not result.is_duplicate:
                if result.reset_detected:
                    LOGGER.warning(
                        "Sensor reset detected for %s — flushing FFT buffer",
                        client_id,
                    )
                    self.processor.flush_client_buffer(client_id)
                record = self.registry.get(client_id)
                sample_rate_hz = record.sample_rate_hz if record is not None else None
                self.processor.ingest(
                    client_id, msg.samples, sample_rate_hz=sample_rate_hz, t0_us=msg.t0_us
                )
            if self.transport is not None:
                ack_payload = pack_data_ack(msg.client_id, msg.seq)
                self.transport.sendto(ack_payload, addr)
        except Exception:
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
