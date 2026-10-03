"""Shared builders for runtime and registry lifecycle tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, create_autospec

import numpy as np

from vibesensor.app.lifecycle import LifecycleManager, LifecycleRuntime
from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.protocol_messages import DataMessage, HelloMessage
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.udp_control_tx import UDPControlPlane
from vibesensor.live.broadcaster import LiveBroadcaster
from vibesensor.live.processing_loop import ProcessingLoop, ProcessingLoopState
from vibesensor.recording.raw_capture_writer import RunRawCaptureWriter
from vibesensor.recording.recorder import RunRecorder
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.obd.service import ObdService
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.updates.manager import UpdateManager
from vibesensor.web.health_state import RuntimeHealthState


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
    control_host: str = "0.0.0.0"
    control_port: int = 5006


@dataclass(slots=True)
class StubLoggingConfig:
    shutdown_analysis_timeout_s: float = 5.0
    history_db_path: str = ":memory:"


@dataclass(slots=True)
class StubGpsConfig:
    gps_enabled: bool = True


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
        kwargs["db"] = db if isinstance(db, HistoryDB) else db
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
    config = overrides.pop("config", StubConfig(processing=StubProcessingConfig()))
    registry = overrides.pop("registry", StubRegistry())
    processor = overrides.pop("processor", StubProcessor())
    control_plane = overrides.pop("control_plane", create_autospec(UDPControlPlane, instance=True))
    gps_monitor = overrides.pop("gps_monitor", create_autospec(GPSSpeedMonitor, instance=True))
    obd_runner = overrides.pop("obd_runner", create_autospec(ObdService, instance=True))
    if not isinstance(getattr(obd_runner, "run", None), AsyncMock):
        obd_runner.run = AsyncMock(side_effect=asyncio.CancelledError)
    history_db = overrides.pop("history_db", create_autospec(HistoryDB, instance=True))
    diagnostics = overrides.pop("run_recorder", None)
    if diagnostics is None:
        diagnostics = create_autospec(RunRecorder, instance=True)
        diagnostics.raw_capture = create_autospec(RunRawCaptureWriter, instance=True)
    update_manager = overrides.pop("update_manager", create_autospec(UpdateManager, instance=True))
    esp_flash_manager = overrides.pop(
        "esp_flash_manager", create_autospec(EspFlashManager, instance=True)
    )
    ingest_diagnostics = overrides.pop("ingest_diagnostics", IngestDiagnosticsCollector())
    processing_state = ProcessingLoopState()
    health_state = RuntimeHealthState()
    lifecycle_runtime = LifecycleRuntime(
        health_state=health_state,
        history_db_path=config.logging.history_db_path,
        udp_data_host=config.udp.data_host,
        udp_data_port=config.udp.data_port,
        shutdown_analysis_timeout_s=config.logging.shutdown_analysis_timeout_s,
        registry=registry,
        processor=processor,
        ingest_diagnostics=ingest_diagnostics,
        control_plane=control_plane,
        processing_loop=ProcessingLoop(
            state=processing_state,
            fft_update_hz=config.processing.fft_update_hz,
            sample_rate_hz=config.processing.sample_rate_hz,
            fft_n=config.processing.fft_n,
            registry=registry,
            processor=processor,
            control_plane=control_plane,
        ),
        ws_broadcaster=overrides.pop(
            "ws_broadcaster", create_autospec(LiveBroadcaster, instance=True)
        ),
        run_recorder=diagnostics,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        history_db=history_db,
    )
    lifecycle = LifecycleManager(runtime=lifecycle_runtime, start_udp_receiver=AsyncMock())
    for name, value in overrides.items():
        setattr(lifecycle_runtime, name, value)
    return lifecycle_runtime, lifecycle
