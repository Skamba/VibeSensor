from __future__ import annotations

import asyncio
import random
import time

from .protocol import (
    MSG_ACK,
    MSG_HELLO,
    ProtocolError,
    pack_cmd_identify,
    parse_ack,
    parse_client_id,
    parse_hello,
)
from .registry import ClientRegistry


class ControlDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, registry: ClientRegistry):
        self.registry = registry
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data:
            return
        msg_type = data[0]
        now_ts = time.time()

        try:
            if msg_type == MSG_HELLO:
                hello = parse_hello(data)
                self.registry.update_from_hello(hello, addr, now_ts)
            elif msg_type == MSG_ACK:
                ack = parse_ack(data)
                self.registry.update_from_ack(ack, now_ts)
        except ProtocolError:
            client_id = data[2:8].hex() if len(data) >= 8 else None
            self.registry.note_parse_error(client_id)


class UDPControlPlane:
    def __init__(self, registry: ClientRegistry, bind_host: str, bind_port: int):
        self.registry = registry
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.protocol = ControlDatagramProtocol(registry)
        self.transport: asyncio.DatagramTransport | None = None
        self._cmd_seq = random.randint(1, 1_000_000)

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self.protocol,
            local_addr=(self.bind_host, self.bind_port),
        )
        self.transport = transport

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def send_identify(self, client_id: str, duration_ms: int) -> tuple[bool, int | None]:
        if self.transport is None:
            return False, None
        try:
            normalized_client_id = parse_client_id(client_id).hex()
        except ValueError:
            return False, None

        record = self.registry.get(normalized_client_id)
        if record is None or record.control_addr is None:
            return False, None

        self._cmd_seq = (self._cmd_seq + 1) & 0xFFFFFFFF
        payload = pack_cmd_identify(parse_client_id(record.client_id), self._cmd_seq, duration_ms)
        self.transport.sendto(payload, record.control_addr)
        self.registry.mark_cmd_sent(normalized_client_id, self._cmd_seq)
        return True, self._cmd_seq
