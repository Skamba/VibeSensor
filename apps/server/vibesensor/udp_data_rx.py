from __future__ import annotations

import asyncio
import logging
import time

from .processing import SignalProcessor
from .protocol import MSG_DATA, ProtocolError, extract_client_id_hex, pack_data_ack, parse_data
from .registry import ClientRegistry

LOGGER = logging.getLogger(__name__)


class DataDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, registry: ClientRegistry, processor: SignalProcessor):
        self.registry = registry
        self.processor = processor
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data:
            return
        if data[0] != MSG_DATA:
            return

        try:
            msg = parse_data(data)
        except ProtocolError as exc:
            client_id = extract_client_id_hex(data)
            LOGGER.debug("DATA parse error from %s (client=%s): %s", addr, client_id, exc)
            self.registry.note_parse_error(client_id)
            return

        try:
            now_ts = time.time()
            client_id = msg.client_id.hex()
            self.registry.update_from_data(msg, addr, now_ts)
            record = self.registry.get(client_id)
            sample_rate_hz = record.sample_rate_hz if record is not None else None
            self.processor.ingest(client_id, msg.samples, sample_rate_hz=sample_rate_hz)
            if self.transport is not None:
                ack_payload = pack_data_ack(msg.client_id, msg.seq)
                self.transport.sendto(ack_payload, addr)
        except Exception:
            LOGGER.debug(
                "Error processing datagram from %s: %s", addr, msg.client_id.hex(), exc_info=True
            )


async def start_udp_data_receiver(
    host: str,
    port: int,
    registry: ClientRegistry,
    processor: SignalProcessor,
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DataDatagramProtocol(registry=registry, processor=processor),
        local_addr=(host, port),
    )
    return transport
