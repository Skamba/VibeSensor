"""Coverage for broadcaster transport behavior independent of payload projection."""

from __future__ import annotations

from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService
from vibesensor.shared.types.payload_types import (
    SCHEMA_VERSION,
    ClientApiRow,
    LiveWsPayload,
    RotationalSpeedsPayload,
)


def _client_row(client_id: str, name: str) -> ClientApiRow:
    return {
        "id": client_id,
        "mac_address": client_id,
        "name": name,
        "connected": True,
        "location_code": "",
        "firmware_version": "fw",
        "sample_rate_hz": 800,
        "last_seen_age_ms": 0,
        "frames_total": 0,
        "dropped_frames": 0,
        "frame_samples": 200,
    }


def _rotational_payload() -> RotationalSpeedsPayload:
    return {
        "basis_speed_source": "gps",
        "wheel": {"rpm": 1.0, "mode": "calculated", "reason": None},
        "driveshaft": {"rpm": 1.0, "mode": "calculated", "reason": None},
        "engine": {"rpm": 1.0, "mode": "calculated", "reason": None},
        "order_bands": None,
    }


def _shared_payload(
    *,
    clients: list[ClientApiRow] | None = None,
    server_time: str = "2026-04-05T00:00:00Z",
) -> LiveWsPayload:
    return {
        "schema_version": SCHEMA_VERSION,
        "server_time": server_time,
        "speed_mps": 12.5,
        "clients": clients or [],
        "selected_client_id": None,
        "rotational_speeds": _rotational_payload(),
        "spectra": {"freq": [], "clients": {}},
    }


class _StubPayloadSource:
    def __init__(self, payloads: list[LiveWsPayload] | None = None) -> None:
        self.calls: list[bool] = []
        self._payloads = payloads or [_shared_payload()]

    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload:
        self.calls.append(include_heavy)
        index = min(len(self.calls) - 1, len(self._payloads) - 1)
        return self._payloads[index]


def test_build_ws_payload_preserves_shared_payload_and_explicit_selection() -> None:
    payload_source = _StubPayloadSource(
        [_shared_payload(clients=[_client_row("aaaaaaaaaaaa", "front-left")])]
    )
    ws_broadcast = WsBroadcastService(
        ui_push_hz=10,
        ui_heavy_push_hz=4,
        payload_source=payload_source,
    )

    payload = ws_broadcast.build_payload(selected_client="aaaaaaaaaaaa")

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["server_time"] == "2026-04-05T00:00:00Z"
    assert payload["speed_mps"] == 12.5
    assert payload["clients"][0]["id"] == "aaaaaaaaaaaa"
    assert payload["selected_client_id"] == "aaaaaaaaaaaa"
    assert payload["rotational_speeds"]["basis_speed_source"] == "gps"
    assert "spectra" in payload


def test_build_ws_payload_auto_selects_first_client() -> None:
    payload_source = _StubPayloadSource(
        [
            _shared_payload(
                clients=[
                    _client_row("aaaaaaaaaaaa", "front-left"),
                    _client_row("bbbbbbbbbbbb", "rear-right"),
                ]
            )
        ]
    )
    ws_broadcast = WsBroadcastService(
        ui_push_hz=10,
        ui_heavy_push_hz=4,
        payload_source=payload_source,
    )

    payload = ws_broadcast.build_payload(selected_client=None)

    assert payload["selected_client_id"] == "aaaaaaaaaaaa"


def test_build_ws_payload_no_clients_keeps_selection_empty() -> None:
    ws_broadcast = WsBroadcastService(
        ui_push_hz=10,
        ui_heavy_push_hz=4,
        payload_source=_StubPayloadSource([_shared_payload(clients=[])]),
    )

    payload = ws_broadcast.build_payload(selected_client=None)

    assert payload["clients"] == []
    assert payload["selected_client_id"] is None


def test_build_ws_payload_reuses_shared_payload_per_tick() -> None:
    payload_source = _StubPayloadSource(
        [
            _shared_payload(
                clients=[
                    _client_row("aaaaaaaaaaaa", "front-left"),
                    _client_row("bbbbbbbbbbbb", "rear-right"),
                ],
                server_time="2026-04-05T00:00:00Z",
            ),
            _shared_payload(
                clients=[_client_row("aaaaaaaaaaaa", "front-left")],
                server_time="2026-04-05T00:00:01Z",
            ),
        ]
    )
    ws_broadcast = WsBroadcastService(
        ui_push_hz=10,
        ui_heavy_push_hz=2,
        payload_source=payload_source,
    )

    first_payload = ws_broadcast.build_payload(selected_client="aaaaaaaaaaaa")
    second_payload = ws_broadcast.build_payload(selected_client="bbbbbbbbbbbb")

    assert payload_source.calls == [True]
    assert first_payload["server_time"] == second_payload["server_time"]
    assert first_payload["selected_client_id"] == "aaaaaaaaaaaa"
    assert second_payload["selected_client_id"] == "bbbbbbbbbbbb"

    ws_broadcast.on_tick()
    third_payload = ws_broadcast.build_payload(selected_client=None)

    assert payload_source.calls == [True, False]
    assert third_payload["server_time"] == "2026-04-05T00:00:01Z"
    assert third_payload["selected_client_id"] == "aaaaaaaaaaaa"


def test_on_ws_broadcast_tick_toggles_heavy_and_requests_matching_payload_weight() -> None:
    payload_source = _StubPayloadSource([_shared_payload()] * 6)
    ws_broadcast = WsBroadcastService(
        ui_push_hz=10,
        ui_heavy_push_hz=2,
        payload_source=payload_source,
    )

    ws_broadcast.build_payload(selected_client=None)
    for _ in range(5):
        ws_broadcast.on_tick()
        ws_broadcast.build_payload(selected_client=None)

    assert payload_source.calls == [True, False, False, False, False, True]
