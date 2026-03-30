from __future__ import annotations

from vibesensor.adapters.gps.gps_transport import GPSTransportState
from vibesensor.adapters.gps.gps_transport_updates import (
    apply_tpv,
    normalize_tpv_payload,
)
from vibesensor.adapters.gps.gpsd_message_handler import NormalizedTpvData


def test_normalize_tpv_payload_uses_custom_readers() -> None:
    payload = {
        "mode": "ignored",
        "speed": 6.0,
        "epx": "ignored",
        "epy": "ignored",
        "epv": "ignored",
        "device": "/dev/ttyACM0",
    }

    normalized = normalize_tpv_payload(
        payload,
        tpv_mode=lambda _payload: 2,
        read_metric=lambda _payload, field: {"epx": 9.0, "epy": 8.0, "epv": 7.0}[field],
    )

    assert normalized == NormalizedTpvData(
        mode=2,
        speed=6.0,
        epx=9.0,
        epy=8.0,
        epv=7.0,
        device="/dev/ttyACM0",
    )


def test_apply_tpv_preserves_existing_device_when_payload_device_missing() -> None:
    transport = GPSTransportState(gps_enabled=True)
    transport.device_info = "/dev/ttyUSB0"

    apply_tpv(
        transport,
        NormalizedTpvData(mode=3, speed=8.0, epx=1.0, epy=2.0, epv=3.0, device=None),
        monotonic=lambda: 123.0,
    )

    assert transport.device_info == "/dev/ttyUSB0"
    assert transport.speed_mps == 8.0
    assert transport.last_update_ts == 123.0


def test_ingest_message_uses_custom_readers_before_delegating_to_apply_tpv(
    monkeypatch,
) -> None:
    transport = GPSTransportState(gps_enabled=True)
    captured: list[NormalizedTpvData] = []

    monkeypatch.setattr(transport, "_apply_tpv", lambda tpv: captured.append(tpv))

    transport.ingest_message(
        {
            "class": "TPV",
            "mode": "ignored",
            "speed": 4.5,
            "epx": "ignored",
            "epy": "ignored",
            "epv": "ignored",
            "device": "/dev/ttyACM1",
        },
        tpv_mode=lambda _payload: 2,
        read_metric=lambda _payload, field: {"epx": 1.0, "epy": 2.0, "epv": 3.0}[field],
    )

    assert captured == [
        NormalizedTpvData(
            mode=2,
            speed=4.5,
            epx=1.0,
            epy=2.0,
            epv=3.0,
            device="/dev/ttyACM1",
        )
    ]
