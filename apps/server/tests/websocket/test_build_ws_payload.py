from __future__ import annotations

import os

os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vibesensor.runtime import RuntimeState

# ---------------------------------------------------------------------------
# Minimal stubs – only implement methods called by build_ws_payload / on_ws_broadcast_tick
# ---------------------------------------------------------------------------


class _StubRegistry:
    def __init__(self, clients: list[dict[str, Any]] | None = None) -> None:
        self._clients = clients or []
        self.snapshot_calls = 0

    def snapshot_for_api(self, now: float | None = None) -> list[dict[str, Any]]:
        self.snapshot_calls += 1
        return list(self._clients)


class _StubProcessor:
    def __init__(self) -> None:
        self.recent_data_calls = 0
        self.multi_spectrum_calls = 0

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        self.recent_data_calls += 1
        return list(client_ids)

    def multi_spectrum_payload(self, client_ids: list[str]) -> dict[str, Any]:
        self.multi_spectrum_calls += 1
        return {"freq": [], "clients": {cid: {} for cid in client_ids}}

    def selected_payload(self, client_id: str) -> dict[str, Any]:
        return {"client_id": client_id, "waveform": {}, "spectrum": {}}


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

    def update_speed_state(self) -> None:
        pass


class _StubAnalysisSettings:
    def __init__(self) -> None:
        self.snapshot_calls = 0

    def snapshot(self) -> dict[str, float]:
        self.snapshot_calls += 1
        return {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        }


class _StubMetricsLogger:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self, timeout_s: float = 30.0) -> bool:
        self.shutdown_calls += 1
        return True


class _StubSettingsStore:
    language: str = "en"

    def get_speed_source(self) -> dict[str, Any]:
        return {"speedSource": "gps", "fallbackMode": "manual"}


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
    import vibesensor.runtime as runtime_module
    from vibesensor.runtime.lifecycle import LifecycleManager
    from vibesensor.runtime.processing_loop import ProcessingLoop, ProcessingLoopState
    from vibesensor.runtime.ws_broadcast import WsBroadcastCache, WsBroadcastService

    ingress = runtime_module.RuntimeIngressSubsystem(
        registry=_StubRegistry(clients),  # type: ignore[arg-type]
        processor=_StubProcessor(),  # type: ignore[arg-type]
        control_plane=_SENTINEL,  # type: ignore[arg-type]
        worker_pool=_SENTINEL,  # type: ignore[arg-type]
    )
    settings = runtime_module.RuntimeSettingsSubsystem(
        settings_store=_StubSettingsStore(),  # type: ignore[arg-type]
        analysis_settings=_StubAnalysisSettings(),  # type: ignore[arg-type]
        gps_monitor=_StubGPS(),  # type: ignore[arg-type]
    )
    persistence = runtime_module.RuntimePersistenceSubsystem(  # type: ignore[arg-type]
        history_db=_SENTINEL,
        run_service=_SENTINEL,
        report_service=_SENTINEL,
        export_service=_SENTINEL,
    )
    processing_state = ProcessingLoopState()
    health_state = runtime_module.RuntimeHealthState()
    processing = runtime_module.RuntimeProcessingSubsystem(
        state=processing_state,
        health_state=health_state,
        loop=ProcessingLoop(
            state=processing_state,
            fft_update_hz=4,
            sample_rate_hz=800,
            fft_n=2048,
            ingress=ingress,
        ),
    )
    cache = WsBroadcastCache()
    websocket = runtime_module.RuntimeWebsocketSubsystem(
        hub=_SENTINEL,  # type: ignore[arg-type]
        cache=cache,
        broadcast=WsBroadcastService(
            cache=cache,
            ui_push_hz=ui_push_hz,
            ui_heavy_push_hz=ui_heavy_push_hz,
            ingress=ingress,
            settings=settings,
        ),
    )
    config = _StubConfig(
        processing=_StubProcessingConfig(
            ui_push_hz=ui_push_hz,
            ui_heavy_push_hz=ui_heavy_push_hz,
        ),
    )
    state = runtime_module.RuntimeState(
        config=config,  # type: ignore[arg-type]
        ingress=ingress,
        settings=settings,
        metrics_logger=_StubMetricsLogger(),  # type: ignore[arg-type]
        persistence=persistence,
        update_manager=_SENTINEL,  # type: ignore[arg-type]
        esp_flash_manager=_SENTINEL,  # type: ignore[arg-type]
        processing=processing,
        websocket=websocket,
        lifecycle=LifecycleManager(
            config=config,  # type: ignore[arg-type]
            ingress=ingress,
            settings=settings,
            metrics_logger=_StubMetricsLogger(),  # type: ignore[arg-type]
            persistence=persistence,
            update_manager=_SENTINEL,  # type: ignore[arg-type]
            esp_flash_manager=_SENTINEL,  # type: ignore[arg-type]
            processing=processing,
            websocket=websocket,
        ),
    )
    state.websocket.cache.include_heavy = ws_include_heavy
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_TWO_CLIENTS = [
    {"id": "aaa", "name": "front-left"},
    {"id": "bbb", "name": "rear-right"},
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
    payload = state.websocket.broadcast.build_payload(selected_client="aaa")

    # Always-present keys
    for key in ("server_time", "speed_mps", "clients", "selected_client_id", "rotational_speeds"):
        assert key in payload, f"missing key: {key}"

    # Heavy-tick keys
    assert "spectra" in payload, "missing heavy key: spectra"

    assert payload["speed_mps"] == 12.5
    assert payload["selected_client_id"] == "aaa"
    assert len(payload["clients"]) == 2
    _assert_rotational(payload["rotational_speeds"], rpm_positive=True)


def test_build_ws_payload_light_tick_omits_spectra_and_selected() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=False)
    payload = state.websocket.broadcast.build_payload(selected_client="aaa")

    assert "spectra" not in payload


def test_build_ws_payload_auto_selects_first_client() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    payload = state.websocket.broadcast.build_payload(selected_client=None)

    assert payload["selected_client_id"] == "aaa"


def test_build_ws_payload_no_clients() -> None:
    state = _make_state(clients=[], ws_include_heavy=True)
    payload = state.websocket.broadcast.build_payload(selected_client=None)

    assert payload["clients"] == []
    assert payload["selected_client_id"] is None


def test_build_ws_payload_reuses_shared_payload_per_tick() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    registry = state.ingress.registry
    processor = state.ingress.processor
    gps = state.settings.gps_monitor
    analysis_settings = state.settings.analysis_settings
    assert isinstance(registry, _StubRegistry)
    assert isinstance(processor, _StubProcessor)
    assert isinstance(gps, _StubGPS)
    assert isinstance(analysis_settings, _StubAnalysisSettings)

    state.websocket.cache.tick = 77
    payload_aaa = state.websocket.broadcast.build_payload(selected_client="aaa")
    payload_bbb = state.websocket.broadcast.build_payload(selected_client="bbb")

    assert payload_aaa["selected_client_id"] == "aaa"
    assert payload_bbb["selected_client_id"] == "bbb"
    assert payload_aaa["server_time"] == payload_bbb["server_time"]
    assert payload_aaa["clients"] == payload_bbb["clients"]
    assert registry.snapshot_calls == 1
    assert processor.recent_data_calls == 1
    assert processor.multi_spectrum_calls == 1
    assert gps.resolve_calls == 1
    assert analysis_settings.snapshot_calls == 1


def test_on_ws_broadcast_tick_toggles_heavy() -> None:
    # ui_push_hz=10, ui_heavy_push_hz=2 → heavy_every=5
    state = _make_state(ui_push_hz=10, ui_heavy_push_hz=2)
    state.websocket.cache.tick = 0
    state.websocket.cache.include_heavy = True  # initial

    results: list[bool] = []
    for _ in range(10):
        state.websocket.broadcast.on_tick()
        results.append(state.websocket.cache.include_heavy)

    # Ticks 1..10: heavy at tick 5 and 10 (tick % 5 == 0)
    assert results == [False, False, False, False, True, False, False, False, False, True]


def test_build_ws_payload_rotational_speeds_include_reason_when_speed_unavailable() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    gps = state.settings.gps_monitor
    assert isinstance(gps, _StubGPS)
    gps.effective_speed_mps = None

    payload = state.websocket.broadcast.build_payload(selected_client="aaa")
    _assert_rotational(payload["rotational_speeds"], reason="speed_unavailable")
