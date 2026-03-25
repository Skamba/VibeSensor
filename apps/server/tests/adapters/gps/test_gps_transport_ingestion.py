from __future__ import annotations

from vibesensor.adapters.gps.gps_transport import GPSTransportState
from vibesensor.adapters.gps.gpsd_message_handler import NormalizedTpvData


def test_ingest_tpv_delegates_normalized_payload_to_apply_tpv(
    monkeypatch,
) -> None:
    transport = GPSTransportState(gps_enabled=True)
    captured: list[NormalizedTpvData] = []

    def _capture(tpv: NormalizedTpvData) -> None:
        captured.append(tpv)

    monkeypatch.setattr(transport, "_apply_tpv", _capture)

    transport.ingest_tpv(
        {
            "mode": 3,
            "speed": 12.5,
            "epx": 1.2,
            "epy": 2.3,
            "epv": 3.4,
            "device": "/dev/ttyUSB0",
        }
    )

    assert captured == [
        NormalizedTpvData(
            mode=3,
            speed=12.5,
            epx=1.2,
            epy=2.3,
            epv=3.4,
            device="/dev/ttyUSB0",
        )
    ]


def test_ingest_tpv_uses_custom_readers_before_delegating(
    monkeypatch,
) -> None:
    transport = GPSTransportState(gps_enabled=True)
    captured: list[NormalizedTpvData] = []

    def _capture(tpv: NormalizedTpvData) -> None:
        captured.append(tpv)

    def _mode_reader(_payload: object) -> int:
        return 2

    def _metric_reader(_payload: object, field: str) -> float:
        return {"epx": 9.0, "epy": 8.0, "epv": 7.0}[field]

    monkeypatch.setattr(transport, "_apply_tpv", _capture)

    transport.ingest_tpv(
        {
            "mode": "ignored",
            "speed": 6.0,
            "epx": "ignored",
            "epy": "ignored",
            "epv": "ignored",
            "device": "/dev/ttyACM0",
        },
        tpv_mode=_mode_reader,
        read_metric=_metric_reader,
    )

    assert captured == [
        NormalizedTpvData(
            mode=2,
            speed=6.0,
            epx=9.0,
            epy=8.0,
            epv=7.0,
            device="/dev/ttyACM0",
        )
    ]


def test_ingest_tpv_matches_ingest_message_snapshot_for_equivalent_payload(
    monkeypatch,
) -> None:
    raw_transport = GPSTransportState(gps_enabled=True)
    message_transport = GPSTransportState(gps_enabled=True)
    monotonic_value = 1234.5

    monkeypatch.setattr(
        "vibesensor.adapters.gps.gps_transport.time.monotonic",
        lambda: monotonic_value,
    )

    raw_transport.ingest_tpv(
        {
            "mode": 3,
            "speed": 18.0,
            "epx": 1.2,
            "epy": 2.3,
            "epv": 3.4,
            "device": "/dev/ttyUSB0",
        }
    )
    message_transport.ingest_message(
        {
            "class": "TPV",
            "mode": 3,
            "speed": 18.0,
            "epx": 1.2,
            "epy": 2.3,
            "epv": 3.4,
            "device": "/dev/ttyUSB0",
        }
    )

    assert raw_transport.snapshot() == message_transport.snapshot()
