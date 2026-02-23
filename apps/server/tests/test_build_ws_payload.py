from __future__ import annotations

import os

os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vibesensor.app import RuntimeState

# ---------------------------------------------------------------------------
# Minimal stubs – only implement methods called by build_ws_payload / on_ws_broadcast_tick
# ---------------------------------------------------------------------------


class _StubRegistry:
    def __init__(self, clients: list[dict[str, Any]] | None = None) -> None:
        self._clients = clients or []

    def snapshot_for_api(self, now: float | None = None) -> list[dict[str, Any]]:
        return list(self._clients)


class _StubProcessor:
    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)

    def multi_spectrum_payload(self, client_ids: list[str]) -> dict[str, Any]:
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

    def resolve_speed(self) -> _SpeedResolution:
        return _SpeedResolution(self.effective_speed_mps, self.fallback_active, "gps")

    def update_speed_state(self) -> None:
        pass


class _StubAnalysisSettings:
    def snapshot(self) -> dict[str, float]:
        return {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
        }


class _StubMetricsLogger:
    def __init__(self) -> None:
        self.analysis_snapshot_calls = 0

    def analysis_snapshot(self) -> tuple[dict[str, object], list[dict[str, object]]]:
        self.analysis_snapshot_calls += 1
        return {"run_id": f"live-{self.analysis_snapshot_calls}"}, [
            {"call": self.analysis_snapshot_calls}
        ]


class _StubDiagnostics:
    def update(self, **kwargs: Any) -> dict[str, Any]:
        return {"matrix": {}, "findings": []}


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
    from vibesensor.app import RuntimeState

    return RuntimeState(
        config=_StubConfig(
            processing=_StubProcessingConfig(
                ui_push_hz=ui_push_hz,
                ui_heavy_push_hz=ui_heavy_push_hz,
            )
        ),  # type: ignore[arg-type]
        registry=_StubRegistry(clients),  # type: ignore[arg-type]
        processor=_StubProcessor(),  # type: ignore[arg-type]
        control_plane=_SENTINEL,  # type: ignore[arg-type]
        ws_hub=_SENTINEL,  # type: ignore[arg-type]
        gps_monitor=_StubGPS(),  # type: ignore[arg-type]
        analysis_settings=_StubAnalysisSettings(),  # type: ignore[arg-type]
        metrics_logger=_StubMetricsLogger(),  # type: ignore[arg-type]
        live_diagnostics=_StubDiagnostics(),  # type: ignore[arg-type]
        settings_store=_StubSettingsStore(),  # type: ignore[arg-type]
        history_db=_SENTINEL,  # type: ignore[arg-type]
        update_manager=_SENTINEL,  # type: ignore[arg-type]
        ws_include_heavy=ws_include_heavy,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_TWO_CLIENTS = [
    {"id": "aaa", "name": "front-left"},
    {"id": "bbb", "name": "rear-right"},
]


def test_build_ws_payload_returns_required_keys() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    payload = state.build_ws_payload(selected_client="aaa")

    # Always-present keys
    for key in ("server_time", "speed_mps", "clients", "selected_client_id", "rotational_speeds"):
        assert key in payload, f"missing key: {key}"

    # Heavy-tick keys
    for key in ("spectra", "selected", "diagnostics"):
        assert key in payload, f"missing heavy key: {key}"

    assert payload["speed_mps"] == 12.5
    assert payload["selected_client_id"] == "aaa"
    assert len(payload["clients"]) == 2
    rotational = payload["rotational_speeds"]
    assert rotational["basis_speed_source"] == "gps"
    for key in ("wheel", "driveshaft", "engine"):
        assert rotational[key]["mode"] == "calculated"
        assert rotational[key]["reason"] is None
        assert isinstance(rotational[key]["rpm"], float)
        assert rotational[key]["rpm"] > 0


def test_build_ws_payload_light_tick_omits_spectra_and_selected() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=False)
    payload = state.build_ws_payload(selected_client="aaa")

    assert "spectra" not in payload
    assert "selected" not in payload
    # diagnostics is always present
    assert "diagnostics" in payload


def test_build_ws_payload_auto_selects_first_client() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    payload = state.build_ws_payload(selected_client=None)

    assert payload["selected_client_id"] == "aaa"


def test_build_ws_payload_no_clients() -> None:
    state = _make_state(clients=[], ws_include_heavy=True)
    payload = state.build_ws_payload(selected_client=None)

    assert payload["clients"] == []
    assert payload["selected_client_id"] is None
    # selected should be empty dict when active is None
    assert payload["selected"] == {}


def test_build_ws_payload_light_tick_reuses_cached_analysis_snapshot() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)

    state.build_ws_payload(selected_client="aaa")
    metrics_logger = state.metrics_logger
    assert isinstance(metrics_logger, _StubMetricsLogger)
    assert metrics_logger.analysis_snapshot_calls == 1

    state.ws_include_heavy = False
    state.build_ws_payload(selected_client="aaa")

    assert metrics_logger.analysis_snapshot_calls == 1


def test_build_ws_payload_light_tick_without_cache_still_collects_snapshot() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=False)

    state.build_ws_payload(selected_client="aaa")
    metrics_logger = state.metrics_logger

    assert isinstance(metrics_logger, _StubMetricsLogger)
    assert metrics_logger.analysis_snapshot_calls == 1


def test_on_ws_broadcast_tick_toggles_heavy() -> None:
    # ui_push_hz=10, ui_heavy_push_hz=2 → heavy_every=5
    state = _make_state(ui_push_hz=10, ui_heavy_push_hz=2)
    state.ws_tick = 0
    state.ws_include_heavy = True  # initial

    results: list[bool] = []
    for _ in range(10):
        state.on_ws_broadcast_tick()
        results.append(state.ws_include_heavy)

    # Ticks 1..10: heavy at tick 5 and 10 (tick % 5 == 0)
    assert results == [False, False, False, False, True, False, False, False, False, True]


def test_build_ws_payload_rotational_speeds_include_reason_when_speed_unavailable() -> None:
    state = _make_state(clients=_TWO_CLIENTS, ws_include_heavy=True)
    gps = state.gps_monitor
    assert isinstance(gps, _StubGPS)
    gps.effective_speed_mps = None

    payload = state.build_ws_payload(selected_client="aaa")
    rotational = payload["rotational_speeds"]

    assert rotational["basis_speed_source"] == "gps"
    for key in ("wheel", "driveshaft", "engine"):
        assert rotational[key]["rpm"] is None
        assert rotational[key]["mode"] == "calculated"
        assert rotational[key]["reason"] == "speed_unavailable"
