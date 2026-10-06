from __future__ import annotations

from vibesensor.speed.gps_transport import GPSTransportState
from vibesensor.speed.gpsd_message_handler import NormalizedTpvData


def test_ingest_message_delegates_normalized_tpv_to_apply_tpv(
    monkeypatch,
) -> None:
    transport = GPSTransportState(gps_enabled=True)
    captured: list[NormalizedTpvData] = []

    def _capture(tpv: NormalizedTpvData) -> None:
        captured.append(tpv)

    monkeypatch.setattr(transport, "_apply_tpv", _capture)

    assert transport.ingest_message(
        {
            "class": "TPV",
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


def test_ingest_message_uses_custom_tpv_readers_before_delegating(
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

    assert transport.ingest_message(
        {
            "class": "TPV",
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
