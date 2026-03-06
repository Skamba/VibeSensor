"""UDP control transmitter — sends command/ack messages to ESP32 sensors.

``UDPControlTxProtocol`` is an asyncio ``DatagramProtocol`` that builds and
transmits binary control frames (``CmdMessage``, ``AckMessage``) to sensor
nodes over the control UDP socket.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from typing import cast

from .protocol import (
    MSG_ACK,
    MSG_DATA_ACK,
    MSG_HELLO,
    ProtocolError,
    extract_client_id_hex,
    pack_cmd_identify,
    pack_cmd_sync_clock,
    parse_ack,
    parse_client_id,
    parse_hello,
)
from .registry import ClientRegistry

LOGGER = logging.getLogger(__name__)

__all__ = ["UDPControlPlane"]

_US_PER_SEC: int = 1_000_000


class ControlDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, registry: ClientRegistry):
        self.registry = registry
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data:
            return
        msg_type = data[0]
        now_ts = time.time()
        registry = self.registry

        try:
            if msg_type == MSG_HELLO:
                hello = parse_hello(data)
                registry.update_from_hello(hello, addr, now_ts)
            elif msg_type == MSG_ACK:
                ack = parse_ack(data)
                LOGGER.info("ACK from %s: cmd_seq=%s status=%s", addr, ack.cmd_seq, ack.status)
                registry.update_from_ack(ack, now_ts)
            elif msg_type == MSG_DATA_ACK:
                return
        except ProtocolError as exc:
            client_id = extract_client_id_hex(data)
            LOGGER.debug("Control parse error from %s (client=%s): %s", addr, client_id, exc)
            registry.note_parse_error(client_id)


class UDPControlPlane:
    def __init__(self, registry: ClientRegistry, bind_host: str, bind_port: int):
        self.registry = registry
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.protocol = ControlDatagramProtocol(registry)
        self.transport: asyncio.DatagramTransport | None = None
        self._cmd_seq = random.randint(1, 1_000_000)
        self._cmd_seq_lock = threading.Lock()

    def _next_cmd_seq(self) -> int:
        """Atomically increment and return the next command sequence number."""
        with self._cmd_seq_lock:
            self._cmd_seq = (self._cmd_seq + 1) & 0xFFFFFFFF
            return self._cmd_seq

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

        seq = self._next_cmd_seq()
        payload = pack_cmd_identify(bytes.fromhex(record.client_id), seq, duration_ms)
        self.transport.sendto(payload, record.control_addr)
        self.registry.mark_cmd_sent(normalized_client_id, seq)
        return True, seq

    def broadcast_sync_clock(self) -> int:
        """Send a clock-sync command to every active sensor.

        Returns the number of sensors that received the message.
        """
        transport = self.transport
        if transport is None:
            return 0
        server_time_us = int(time.monotonic() * _US_PER_SEC)
        registry = self.registry
        _fromhex = bytes.fromhex
        _next_seq = self._next_cmd_seq
        _pack = pack_cmd_sync_clock
        _sendto = transport.sendto
        sent = 0
        for client_id in registry.active_client_ids():
            record = registry.get(client_id)
            if record is None or record.control_addr is None:
                continue
            seq = _next_seq()
            payload = _pack(
                _fromhex(record.client_id),
                seq,
                server_time_us,
            )
            _sendto(payload, record.control_addr)
            sent += 1
        return sent
