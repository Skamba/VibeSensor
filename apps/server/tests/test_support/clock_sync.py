"""Drive the server/sensor clock-sync handshake on a ``ClientRegistry``."""

from __future__ import annotations

from vibesensor.ingest.protocol_messages import AckMessage
from vibesensor.ingest.registry import ClientRegistry


def complete_clock_sync(
    registry: ClientRegistry,
    client_id: str,
    *,
    offset_us: int = 0,
    now_mono_s: float = 100.0,
) -> None:
    """Run the two sync exchanges after which a sensor stamps frames on the server clock.

    The first exchange measures the offset; the second carries it with a round
    trip, which is when the sensor applies it. ``offset_us`` is server minus
    device time.
    """
    for cmd_seq, applies_offset in ((1, False), (2, True)):
        server_us = int(now_mono_s * 1_000_000) + cmd_seq
        registry.mark_cmd_sent(
            client_id,
            cmd_seq,
            sync_send_us=server_us,
            sync_applies_offset=applies_offset,
        )
        registry.update_from_ack(
            AckMessage(
                client_id=bytes.fromhex(client_id),
                cmd_seq=cmd_seq,
                status=0,
                device_receive_us=server_us - offset_us,
                device_send_us=server_us - offset_us,
            ),
            now_mono=server_us / 1_000_000,
        )
