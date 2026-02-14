from __future__ import annotations

import asyncio
import time

from .processing import SignalProcessor
from .protocol import MSG_DATA, ProtocolError, parse_data
from .registry import ClientRegistry


class DataDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, registry: ClientRegistry, processor: SignalProcessor):
        self.registry = registry
        self.processor = processor

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data:
            return
        if data[0] != MSG_DATA:
            return

        try:
            msg = parse_data(data)
        except ProtocolError:
            client_id = data[2:8].hex() if len(data) >= 8 else None
            self.registry.note_parse_error(client_id)
            return

        now_ts = time.time()
        client_id = msg.client_id.hex()
        self.registry.update_from_data(msg, addr, now_ts)
        record = self.registry.get(client_id)
        sample_rate_hz = record.sample_rate_hz if record is not None else None
        self.processor.ingest(client_id, msg.samples, sample_rate_hz=sample_rate_hz)


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
