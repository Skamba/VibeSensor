from __future__ import annotations

import os

os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot

if TYPE_CHECKING:
    from vibesensor.app.runtime_state import RuntimeState

# ---------------------------------------------------------------------------
# Minimal stubs – only implement methods called by build_ws_payload / on_ws_broadcast_tick
# ---------------------------------------------------------------------------


class _StubRegistry:
    def __init__(self, clients: list[dict[str, Any]] | None = None) -> None:
        self._clients = clients or []
        self.snapshot_calls = 0

    def active_client_ids(self) -> list[str]:
        return [c["id"] for c in self._clients if "id" in c]

    def client_snapshots(
        self,
        now: float | None = None,
        *,
        now_mono: float | None = None,
        metrics_by_client: dict[str, Any] | None = None,
    ) -> list[ClientSnapshot]:
        del now, now_mono, metrics_by_client
        self.snapshot_calls += 1
        return [
            ClientSnapshot(
                client_id=str(client["id"]),
                name=str(client.get("name", "")),
                connected=bool(client.get("connected", False)),
                location_code=str(client.get("location_code", "")),
                firmware_version=str(client.get("firmware_version", "")),
                sample_rate_hz=int(client.get("sample_rate_hz", 0)),
                frame_samples=int(client.get("frame_samples", 0)),
                last_seen_age_ms=client.get("last_seen_age_ms"),
                frames_total=int(client.get("frames_total", 0)),
                dropped_frames=int(client.get("dropped_frames", 0)),
                latest_metrics=client.get("latest_metrics"),
                reset_count=int(client.get("reset_count", 0)),
                last_reset_time=client.get("last_reset_time"),
            )
            for client in self._clients
        ]


class _StubProcessor:
    def __init__(self) -> None:
        self.recent_data_calls = 0
        self.multi_spectrum_calls = 0

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        self.recent_data_calls += 1
        return list(client_ids)

    def all_latest_metrics(self, client_ids: list[str]) -> dict[str, Any]:
        return {}

    def multi_spectrum_payload(self, client_ids: list[str]) -> dict[str, Any]:
        self.multi_spectrum_calls += 1
        return {"freq": [], "clients": {cid: {} for cid in client_ids}}


class _SpeedResolution:
    """Minimal stand-in for gps_speed.SpeedResolution NamedTuple."""

    def __init__(
        self,
        speed_mps: float | None = 12.5,
        fallback_active: bool = False,
        source: str = "gps",
    ):
        self.speed_mps = speed_mps
        self.fallback_active = fallback_active
        self.source = source


class _StubGPS:
    effective_speed_mps: float | None = 12.5
    gps_enabled: bool = True
    fallback_active: bool = False

    def __init__(self) -> None:
        self.resolve_calls = 0

    def resolve_speed(self) -> _SpeedResolution:
        self.resolve_calls += 1
        return _SpeedResolution(self.effective_speed_mps, self.fallback_active, "gps")

    @property
    def speed_mps(self) -> float | None:
        return self.effective_speed_mps

    def update_speed_state(self) -> None:
        pass


class _StubRunRecorder:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self, timeout_s: float = 30.0) -> bool:
        self.shutdown_calls += 1
        return True


class _StubSettingsStore:
    language: str = "en"

    def __init__(self) -> None:
        self.snapshot_calls = 0

    def get_speed_source(self) -> dict[str, Any]:
        return {"speedSource": "gps"}

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        self.snapshot_calls += 1
        return AnalysisSettingsSnapshot(
            tire_width_mm=285.0,
            tire_aspect_pct=30.0,
            rim_in=21.0,
            final_drive_ratio=3.08,
            current_gear_ratio=0.64,
        )


@dataclass(slots=True)
class _StubProcessingConfig:
    ui_push_hz: int = 10
    ui_heavy_push_hz: int = 4
    sample_rate_hz: int = 800
    waveform_seconds: int = 8
    waveform_display_hz: int = 120
    fft_update_hz: int = 4
    fft_n: int = 2048
    spectrum_max_hz: int = 200
    client_live_ttl_seconds: int = 10
    client_ttl_seconds: int = 120
    accel_scale_g_per_lsb: float | None = None


@dataclass(slots=True)
class _StubConfig:
    processing: _StubProcessingConfig


# ---------------------------------------------------------------------------
# Helper to build a RuntimeState with stubs
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _make_state(
    clients: list[dict[str, Any]] | None = None,
    ws_include_heavy: bool = True,
    ui_push_hz: int = 10,
    ui_heavy_push_hz: int = 4,
) -> RuntimeState:
    from vibesensor.app.runtime_state import RuntimeState
    from vibesensor.infra.runtime import RuntimeHealthState
    from vibesensor.infra.runtime.processing_loop import ProcessingLoop, ProcessingLoopState
    from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService

    registry = _StubRegistry(clients)
    processor = _StubProcessor()
    gps_monitor = _StubGPS()
    settings_store = _StubSettingsStore()
    processing_state = ProcessingLoopState()
    health_state = RuntimeHealthState()
    config = _StubConfig(
        processing=_StubProcessingConfig(
            ui_push_hz=ui_push_hz,
            ui_heavy_push_hz=ui_heavy_push_hz,
        ),
    )
    state = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=_SENTINEL,
        worker_pool=_SENTINEL,
        settings_store=settings_store,
        gps_monitor=gps_monitor,
        history_db=_SENTINEL,
        processing_loop_state=processing_state,
        health_state=health_state,
        processing_loop=ProcessingLoop(
            state=processing_state,
            fft_update_hz=4,
            sample_rate_hz=800,
            fft_n=2048,
            registry=registry,
            processor=processor,
        ),
        ws_hub=_SENTINEL,
        ws_broadcast=WsBroadcastService(
            ui_push_hz=ui_push_hz,
            ui_heavy_push_hz=ui_heavy_push_hz,
            registry=registry,
            processor=processor,
            gps_monitor=gps_monitor,
            gps_enabled=gps_monitor.gps_enabled,
            settings_store=settings_store,
        ),
        run_recorder=_StubRunRecorder(),
        update_manager=_SENTINEL,
        esp_flash_manager=_SENTINEL,
    )
    state.ws_broadcast.include_heavy = ws_include_heavy
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_TWO_CLIENTS = [
    {"id": "aaaaaaaaaaaa", "name": "front-left"},
    {"id": "bbbbbbbbbbbb", "name": "rear-right"},
]

_ROTATIONAL_KEYS = ("wheel", "driveshaft", "engine")


def _assert_rotational(
    rotational: dict,
    *,
    source: str = "gps",
    mode: str = "calculated",
    reason: str | None = None,
    rpm_positive: bool = False,
) -> None:
    """Validate rotational_speeds sub-dict for all drivetrain components."""
    assert rotational["basis_speed_source"] == source
    for key in _ROTATIONAL_KEYS:
        assert rotational[key]["mode"] == mode
        assert rotational[key]["reason"] == reason
        if rpm_positive:
            assert isinstance(rotational[key]["rpm"], float)
            assert rotational[key]["rpm"] > 0
        else:
            assert rotational[key]["rpm"] is None


def test_build_ws_payload_returns_required_keys() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    payload = state.ws_broadcast.build_payload(selected_client="aaaaaaaaaaaa")

    # Always-present keys
    for key in (
        "schema_version",
        "server_time",
        "speed_mps",
        "clients",
        "selected_client_id",
        "rotational_speeds",
    ):
        assert key in payload, f"missing key: {key}"

    # Heavy-tick keys
    assert "spectra" in payload, "missing heavy key: spectra"

    assert payload["speed_mps"] == 12.5
    assert payload["selected_client_id"] == "aaaaaaaaaaaa"
    assert len(payload["clients"]) == 2
    _assert_rotational(payload["rotational_speeds"], rpm_positive=True)


def test_build_ws_payload_light_tick_omits_only_spectra() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=False)
    payload = state.ws_broadcast.build_payload(selected_client="aaaaaaaaaaaa")

    assert "spectra" not in payload
    assert payload["selected_client_id"] == "aaaaaaaaaaaa"


def test_build_ws_payload_auto_selects_first_client() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    payload = state.ws_broadcast.build_payload(selected_client=None)

    assert payload["selected_client_id"] == "aaaaaaaaaaaa"


def test_build_ws_payload_no_clients() -> None:
    state = _make_state(clients=[], ws_include_heavy=True)
    payload = state.ws_broadcast.build_payload(selected_client=None)

    assert payload["clients"] == []
    assert payload["selected_client_id"] is None


def test_build_ws_payload_reuses_shared_payload_per_tick() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    registry = state.registry
    processor = state.processor
    gps = state.gps_monitor
    settings_store = state.settings_store
    assert isinstance(registry, _StubRegistry)
    assert isinstance(processor, _StubProcessor)
    assert isinstance(gps, _StubGPS)
    assert isinstance(settings_store, _StubSettingsStore)

    state.ws_broadcast.tick = 77
    payload_aaa = state.ws_broadcast.build_payload(selected_client="aaaaaaaaaaaa")
    payload_bbb = state.ws_broadcast.build_payload(selected_client="bbbbbbbbbbbb")

    assert payload_aaa["selected_client_id"] == "aaaaaaaaaaaa"
    assert payload_bbb["selected_client_id"] == "bbbbbbbbbbbb"
    assert payload_aaa["server_time"] == payload_bbb["server_time"]
    assert payload_aaa["clients"] == payload_bbb["clients"]
    assert registry.snapshot_calls == 1
    assert processor.recent_data_calls == 1
    assert processor.multi_spectrum_calls == 1
    assert gps.resolve_calls == 1
    assert settings_store.snapshot_calls == 1


def test_on_ws_broadcast_tick_toggles_heavy() -> None:
    # ui_push_hz=10, ui_heavy_push_hz=2 → heavy_every=5
    state = _make_state(ui_push_hz=10, ui_heavy_push_hz=2)
    state.ws_broadcast.tick = 0
    state.ws_broadcast.include_heavy = True  # initial

    results: list[bool] = []
    for _ in range(10):
        state.ws_broadcast.on_tick()
        results.append(state.ws_broadcast.include_heavy)

    # Ticks 1..10: heavy at tick 5 and 10 (tick % 5 == 0)
    assert results == [False, False, False, False, True, False, False, False, False, True]


def test_build_ws_payload_rotational_speeds_include_reason_when_speed_unavailable() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    gps = state.gps_monitor
    assert isinstance(gps, _StubGPS)
    gps.effective_speed_mps = None

    payload = state.ws_broadcast.build_payload(selected_client="aaaaaaaaaaaa")
    _assert_rotational(payload["rotational_speeds"], reason="speed_unavailable")


def test_build_ws_payload_marks_retained_stale_clients_disconnected(
    tmp_path,
    monkeypatch,
) -> None:
    from vibesensor.adapters.persistence.history_db import HistoryDB
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry
    from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService

    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db, live_ttl_seconds=5.0, retention_ttl_seconds=30.0)
    hello = HelloMessage(
        client_id=bytes.fromhex("001122334455"),
        control_port=9010,
        sample_rate_hz=800,
        name="sensor",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0, now_mono=1.0)

    now = {"wall": 9.0, "mono": 9.0}
    monkeypatch.setattr("vibesensor.infra.runtime.registry.time.time", lambda: now["wall"])
    monkeypatch.setattr("vibesensor.infra.runtime.registry.time.monotonic", lambda: now["mono"])

    ws_broadcast = WsBroadcastService(
        ui_push_hz=10,
        ui_heavy_push_hz=4,
        registry=registry,
        processor=_StubProcessor(),
        gps_monitor=_StubGPS(),
        gps_enabled=True,
        settings_store=_StubSettingsStore(),
    )
    payload = ws_broadcast.build_payload(selected_client=None)
    assert len(payload["clients"]) == 1
    assert payload["clients"][0]["connected"] is False
    assert payload["clients"][0]["last_seen_age_ms"] == 8000
