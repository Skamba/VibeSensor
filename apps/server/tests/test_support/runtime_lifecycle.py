"""Shared builders for runtime and registry lifecycle tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import numpy as np

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.udp.protocol import DataMessage, HelloMessage
from vibesensor.app.runtime_state import RuntimeState
from vibesensor.infra.runtime.lifecycle import LifecycleManager, LifecycleRuntime
from vibesensor.infra.runtime.processing_loop import ProcessingLoop
from vibesensor.infra.runtime.processing_state import ProcessingLoopState
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService
from vibesensor.shared.types.payload_types import SCHEMA_VERSION, LiveWsPayload


@dataclass(slots=True)
class FakeHelloMessage:
    client_id: bytes
    control_port: int
    sample_rate_hz: int
    name: str
    firmware_version: str
    frame_samples: int = 0
    queue_overflow_drops: int = 0


@dataclass(slots=True)
class FakeDataMessage:
    client_id: bytes
    seq: int
    t0_us: int
    sample_count: int


@dataclass(slots=True)
class FakeAckMessage:
    client_id: bytes
    cmd_seq: int
    status: int


class FakeClientNameStore:
    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def list_client_names(self) -> dict[str, str]:
        return dict(self._names)

    def upsert_client_name(self, client_id: str, name: str) -> None:
        self._names[client_id] = name

    def delete_client_name(self, client_id: str) -> bool:
        return self._names.pop(client_id, None) is not None


@dataclass(slots=True)
class StubProcessingConfig:
    fft_update_hz: int = 10
    sample_rate_hz: int = 800
    fft_n: int = 2048
    ui_push_hz: int = 10
    ui_heavy_push_hz: int = 4
    waveform_seconds: int = 8
    waveform_display_hz: int = 120
    spectrum_max_hz: int = 200
    client_live_ttl_seconds: int = 10
    client_ttl_seconds: int = 120
    accel_scale_g_per_lsb: float | None = None
    spectrum_min_hz: int = 5


@dataclass(slots=True)
class StubUDPConfig:
    data_host: str = "0.0.0.0"
    data_port: int = 5005
    data_queue_maxsize: int = 100
    control_host: str = "0.0.0.0"
    control_port: int = 5006


@dataclass(slots=True)
class StubLoggingConfig:
    shutdown_analysis_timeout_s: float = 5.0
    history_db_path: str = ":memory:"
    metrics_log_hz: int = 1
    no_data_timeout_s: int = 10
    persist_history_db: bool = False


@dataclass(slots=True)
class StubGpsConfig:
    gps_enabled: bool = True
    gpsd_host: str = "127.0.0.1"
    gpsd_port: int = 2947


@dataclass(slots=True)
class StubConfig:
    processing: StubProcessingConfig
    udp: StubUDPConfig | None = None
    logging: StubLoggingConfig | None = None
    gps: StubGpsConfig | None = None

    def __post_init__(self) -> None:
        if self.udp is None:
            self.udp = StubUDPConfig()
        if self.logging is None:
            self.logging = StubLoggingConfig()
        if self.gps is None:
            self.gps = StubGpsConfig()


class StubRecord:
    sample_rate_hz: int = 800
    frame_samples: int = 1024


class StubRegistry:
    def __init__(self) -> None:
        self._clients: dict[str, StubRecord] = {}

    def evict_stale(self) -> None:
        pass

    def active_client_ids(self) -> list[str]:
        return list(self._clients.keys())

    def get(self, client_id: str) -> StubRecord | None:
        return self._clients.get(client_id)


class StubProcessor:
    def __init__(self) -> None:
        self.compute_all_calls = 0

    def clients_with_recent_data(self, client_ids: list[str], max_age_s: float = 3.0) -> list[str]:
        return list(client_ids)

    def compute_all(
        self,
        client_ids: list[str],
        sample_rates_hz: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        self.compute_all_calls += 1
        return {}

    def evict_clients(self, active: set[str]) -> None:
        pass


class StubWsPayloadSource:
    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload:
        payload: LiveWsPayload = {
            "schema_version": SCHEMA_VERSION,
            "server_time": "2026-04-05T00:00:00Z",
            "speed_mps": None,
            "clients": [],
            "selected_client_id": None,
            "rotational_speeds": {
                "basis_speed_source": None,
                "wheel": {"rpm": None, "mode": None, "reason": None},
                "driveshaft": {"rpm": None, "mode": None, "reason": None},
                "engine": {"rpm": None, "mode": None, "reason": None},
                "order_bands": None,
            },
        }
        if include_heavy:
            payload["spectra"] = {"freq": [], "clients": {}}
        return payload


def build_history_db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "history.db")


def build_registry(
    *,
    db: object | None = None,
    live_ttl_seconds: float = 10.0,
    retention_ttl_seconds: float = 120.0,
) -> ClientRegistry:
    kwargs: dict[str, object] = {
        "live_ttl_seconds": live_ttl_seconds,
        "retention_ttl_seconds": retention_ttl_seconds,
    }
    if db is not None:
        kwargs["db"] = db
    return ClientRegistry(**kwargs)


def make_hello_message(
    client_id_hex: str = "aabbccddeeff",
    *,
    control_port: int = 9010,
    sample_rate_hz: int = 800,
    name: str = "node-1",
    firmware_version: str = "fw",
    frame_samples: int = 0,
    queue_overflow_drops: int = 0,
) -> HelloMessage:
    return HelloMessage(
        client_id=bytes.fromhex(client_id_hex),
        control_port=control_port,
        sample_rate_hz=sample_rate_hz,
        name=name,
        firmware_version=firmware_version,
        frame_samples=frame_samples,
        queue_overflow_drops=queue_overflow_drops,
    )


def make_data_message(
    client_id: bytes,
    seq: int,
    t0_us: int,
    *,
    sample_count: int = 100,
    samples: np.ndarray | None = None,
) -> DataMessage:
    return DataMessage(
        client_id=client_id,
        seq=seq,
        t0_us=t0_us,
        sample_count=sample_count,
        samples=samples if samples is not None else np.zeros((sample_count, 3), dtype=np.int16),
    )


def build_registry_with_hello(
    tmp_path: Path,
    client_id_hex: str = "aabbccddeeff",
) -> tuple[ClientRegistry, bytes]:
    db = build_history_db(tmp_path)
    registry = build_registry(db=db)
    hello = make_hello_message(client_id_hex)
    registry.update_from_hello(hello, ("10.4.0.2", hello.control_port), now=1.0)
    return registry, hello.client_id


def build_runtime(**overrides: Any):
    import vibesensor.infra.runtime as runtime_module

    config = overrides.pop("config", StubConfig(processing=StubProcessingConfig()))
    registry = overrides.pop("registry", StubRegistry())
    processor = overrides.pop("processor", StubProcessor())
    control_plane = overrides.pop("control_plane", MagicMock())
    worker_pool = overrides.pop("worker_pool", MagicMock())
    settings_reader = overrides.pop("settings_reader", MagicMock())
    gps_monitor = overrides.pop("gps_monitor", MagicMock())
    obd_runner = overrides.pop("obd_runner", MagicMock())
    if not isinstance(getattr(obd_runner, "run", None), AsyncMock):
        obd_runner.run = AsyncMock(side_effect=asyncio.CancelledError)
    history_db = overrides.pop("history_db", MagicMock())
    diagnostics = overrides.pop("run_recorder", MagicMock())
    update_manager = overrides.pop("update_manager", MagicMock())
    esp_flash_manager = overrides.pop("esp_flash_manager", MagicMock())
    payload_source = overrides.pop("payload_source", StubWsPayloadSource())
    processing_state = ProcessingLoopState()
    health_state = runtime_module.RuntimeHealthState()
    rt = RuntimeState(
        config=config,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        worker_pool=worker_pool,
        settings_reader=settings_reader,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        history_db=history_db,
        processing_loop_state=processing_state,
        health_state=health_state,
        processing_loop=ProcessingLoop(
            state=processing_state,
            fft_update_hz=config.processing.fft_update_hz,
            sample_rate_hz=config.processing.sample_rate_hz,
            fft_n=config.processing.fft_n,
            registry=registry,
            processor=processor,
            control_plane=control_plane,
        ),
        ws_hub=overrides.pop("ws_hub", MagicMock()),
        ws_broadcast=WsBroadcastService(
            ui_push_hz=config.processing.ui_push_hz,
            ui_heavy_push_hz=config.processing.ui_heavy_push_hz,
            payload_source=payload_source,
        ),
        run_recorder=diagnostics,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
    )
    lifecycle_runtime = LifecycleRuntime(
        health_state=health_state,
        history_db_path=config.logging.history_db_path,
        udp_data_host=config.udp.data_host,
        udp_data_port=config.udp.data_port,
        udp_data_queue_maxsize=config.udp.data_queue_maxsize,
        gpsd_host=config.gps.gpsd_host,
        gpsd_port=config.gps.gpsd_port,
        shutdown_analysis_timeout_s=config.logging.shutdown_analysis_timeout_s,
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        processing_loop=rt.processing_loop,
        ws_hub=rt.ws_hub,
        ws_broadcast=rt.ws_broadcast,
        run_recorder=diagnostics,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        worker_pool=worker_pool,
        history_db=history_db,
    )
    lifecycle = LifecycleManager(runtime=lifecycle_runtime, start_udp_receiver=AsyncMock())
    if overrides:
        for name, value in overrides.items():
            setattr(rt, name, value)
    return rt, lifecycle
