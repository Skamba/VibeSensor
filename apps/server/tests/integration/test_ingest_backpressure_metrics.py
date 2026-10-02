"""Deterministic ingest/backpressure diagnostics smoke.

This test protects product-risk signals, not throughput certification: UDP queue
age, ACK latency, WebSocket publish latency, raw-capture persistence, and runtime
health projection must stay observable under a bounded multi-sensor burst.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import numpy as np
import pytest
from test_support.polling import async_wait_until

from vibesensor.adapters.persistence.history_db._history_db import HistoryDB
from vibesensor.common.units import KMH_TO_MPS
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.tire_spec import TireSpec
from vibesensor.infra.runtime.health_snapshot import build_system_health_snapshot
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.protocol import pack_data, pack_hello, parse_hello
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.udp_data_rx import DataDatagramProtocol
from vibesensor.live.broadcaster import LiveBroadcaster
from vibesensor.live.payload_types import LiveWsPayload
from vibesensor.live.processing_loop import ProcessingLoopState
from vibesensor.live.processor import SignalProcessor
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.use_cases.run._recorder_types import RunRecorderConfig
from vibesensor.use_cases.run.logger import RunRecorder

_FRAME_N = 256
_SAMPLE_RATE_HZ = 800
_ACCEL_SCALE = 0.0005
# Product-risk ceilings: high enough to avoid normal CI scheduler noise, low
# enough to catch stuck ingest, ACK, or publish paths before they become visible.
_MAX_QUEUE_AGE_MS = 500.0
_MAX_ACK_LATENCY_MS = 500.0
_MAX_WS_PUBLISH_MS = 500.0
_LOCATIONS = ("front-left", "front-right", "rear-left", "rear-right", "body")


@dataclass(frozen=True, slots=True)
class _SensorSpec:
    client_id: bytes
    location: str
    amplitude: float


@dataclass(frozen=True, slots=True)
class _IngestSmokeContext:
    sensors: list[_SensorSpec]
    ingest_diagnostics: IngestDiagnosticsCollector
    registry: ClientRegistry
    processor: SignalProcessor
    gps_monitor: GPSSpeedMonitor
    recorder: RunRecorder
    proto: DataDatagramProtocol
    ws_broadcaster: LiveBroadcaster


class _FakeTransport:
    def sendto(self, _data: bytes, _addr: tuple[str, int]) -> None:
        return None


@pytest.fixture
def history_db(tmp_path: Path) -> Iterator[HistoryDB]:
    db = HistoryDB(tmp_path / "history.db")
    yield db
    db.close()


def _sensor_specs(count: int) -> list[_SensorSpec]:
    amplitudes = (1.0, 0.82, 0.7, 0.58, 0.45)
    return [
        _SensorSpec(
            client_id=(i + 1).to_bytes(6, byteorder="big"),
            location=_LOCATIONS[i],
            amplitude=amplitudes[i],
        )
        for i in range(count)
    ]


def _register_sensors(registry: ClientRegistry, sensors: list[_SensorSpec]) -> None:
    for index, sensor in enumerate(sensors, start=1):
        hello = parse_hello(
            pack_hello(
                sensor.client_id,
                control_port=9000 + index,
                sample_rate_hz=_SAMPLE_RATE_HZ,
                name=f"{sensor.location}-node",
                frame_samples=_FRAME_N,
                firmware_version="fw-test",
            ),
        )
        registry.update_from_hello(hello, ("127.0.0.1", 9000 + index))
        registry.set_location(sensor.client_id.hex(), sensor.location)


def _build_sensor_packet(
    client_id: bytes,
    amplitude: float,
    step: int,
    seq: int,
    wheel_hz: float,
) -> bytes:
    time_axis = (np.arange(_FRAME_N) + step * _FRAME_N) / _SAMPLE_RATE_HZ
    rng = np.random.default_rng(seed=(step << 8) + int.from_bytes(client_id, "big"))
    signal = (
        amplitude * 0.45 * np.sin(2 * math.pi * wheel_hz * time_axis)
        + amplitude * 0.20 * np.sin(2 * math.pi * (2.0 * wheel_hz) * time_axis + 0.4)
        + 0.04 * rng.normal(size=_FRAME_N)
    )
    raw_x = np.clip(np.round(signal / _ACCEL_SCALE), -32768, 32767).astype(np.int16)
    samples_i16 = np.stack([raw_x, np.zeros_like(raw_x), np.zeros_like(raw_x)], axis=1)
    return pack_data(
        client_id,
        seq=seq,
        t0_us=int((step * _FRAME_N / _SAMPLE_RATE_HZ) * 1_000_000),
        samples=samples_i16,
    )


def _sample_rates(registry: ClientRegistry) -> dict[str, int]:
    active_ids = registry.active_client_ids()
    return {
        client_id: int(record.sample_rate_hz)
        for client_id in active_ids
        if (record := registry.get(client_id)) is not None
    }


def _ready_health_state() -> RuntimeHealthState:
    health_state = RuntimeHealthState()
    health_state.mark_ready()
    return health_state


class _IntakePayloadSource:
    """Minimal live payload exposing ingest progress to the broadcaster."""

    def __init__(self, processor: SignalProcessor) -> None:
        self._processor = processor

    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload:
        total = self._processor.intake_stats()["total_ingested_samples"]
        return cast(LiveWsPayload, {"clients": [], "total_ingested_samples": total})


def _build_smoke_context(history_db: HistoryDB) -> _IngestSmokeContext:
    sensor_count = 3
    sensors = _sensor_specs(sensor_count)
    ingest_diagnostics = IngestDiagnosticsCollector()
    registry = ClientRegistry(db=history_db)
    processor = SignalProcessor(
        sample_rate_hz=_SAMPLE_RATE_HZ,
        waveform_seconds=4,
        waveform_display_hz=100,
        fft_n=_FRAME_N,
        spectrum_max_hz=200,
        accel_scale_g_per_lsb=_ACCEL_SCALE,
    )
    gps_monitor = GPSSpeedMonitor(gps_enabled=False)
    recorder = RunRecorder(
        RunRecorderConfig(
            metrics_log_hz=20,
            sensor_model="ADXL345",
            default_sample_rate_hz=_SAMPLE_RATE_HZ,
            fft_window_size_samples=_FRAME_N,
            persist_history_db=True,
        ),
        registry=registry,
        gps_monitor=gps_monitor,
        processor=processor,
        history_db=history_db,
        language_reader=SimpleNamespace(language="en"),
        ingest_diagnostics=ingest_diagnostics,
    )
    proto = DataDatagramProtocol(
        registry=registry,
        processor=processor,
        raw_capture_sink=recorder.raw_capture,
        ingest_diagnostics=ingest_diagnostics,
        queue_maxsize=max(24, sensor_count * 6),
    )
    proto.connection_made(_FakeTransport())
    _register_sensors(registry, sensors)
    return _IngestSmokeContext(
        sensors=sensors,
        ingest_diagnostics=ingest_diagnostics,
        registry=registry,
        processor=processor,
        gps_monitor=gps_monitor,
        recorder=recorder,
        proto=proto,
        ws_broadcaster=LiveBroadcaster(
            payload_source=_IntakePayloadSource(processor),
            ingest_diagnostics=ingest_diagnostics,
            push_hz=60,
            heavy_push_hz=60,
        ),
    )


def _backpressure_wait_state(
    ingest_diagnostics: IngestDiagnosticsCollector,
) -> dict[str, object]:
    udp = ingest_diagnostics.udp_snapshot()
    raw_capture = ingest_diagnostics.raw_capture_snapshot()
    ws_publish = ingest_diagnostics.ws_publish_snapshot()
    return {
        "udp_processed_datagrams": udp.processed_datagrams,
        "udp_queue_depth": udp.queue_depth,
        "raw_capture_queue_depth": raw_capture.queue_depth,
        "ws_publish_ticks": ws_publish.total_publish_ticks,
        "ws_active_connections": ws_publish.active_connections,
    }


async def _assert_async_wait_until(
    description: str,
    predicate: Callable[[], object],
    *,
    timeout_s: float = 2.0,
    state: Callable[[], object],
) -> None:
    assert await async_wait_until(predicate, timeout_s=timeout_s), (
        f"Timed out waiting for {description}; state={state()}"
    )


async def _flush_smoke_records(
    ctx: _IngestSmokeContext,
    run_id: str,
    start_utc: str,
    start_mono: float,
) -> None:
    ctx.processor.compute_all(
        ctx.registry.active_client_ids(),
        sample_rates_hz=_sample_rates(ctx.registry),
    )
    await asyncio.to_thread(
        ctx.recorder._sample_flush.append_records,
        run_id,
        start_utc,
        start_mono,
    )


async def _drive_bounded_sensor_burst(
    ctx: _IngestSmokeContext,
    run_id: str,
    start_utc: str,
    start_mono: float,
    tire_circumference_m: float,
) -> int:
    seq_by_sensor = {sensor.client_id.hex(): 1 for sensor in ctx.sensors}
    deferred_late_seq_by_sensor: dict[str, int] = {}
    expected_processed_datagrams = 0
    for step in range(18):
        speed_kmh = 35.0 + (step % 9) * 4.0
        ctx.gps_monitor.set_speed_override_kmh(speed_kmh)
        wheel_hz = speed_kmh * KMH_TO_MPS / tire_circumference_m
        assert wheel_hz > 0.0
        for index, sensor in enumerate(ctx.sensors):
            sensor_id = sensor.client_id.hex()
            if index == 0 and step == 6:
                deferred_late_seq_by_sensor[sensor_id] = seq_by_sensor[sensor_id]
                seq_by_sensor[sensor_id] += 1
            current_seq = seq_by_sensor[sensor_id]
            ctx.proto.datagram_received(
                _build_sensor_packet(
                    sensor.client_id,
                    sensor.amplitude,
                    step,
                    current_seq,
                    wheel_hz,
                ),
                ("127.0.0.1", 7000 + index),
            )
            expected_processed_datagrams += 1
            seq_by_sensor[sensor_id] = current_seq + 1
            if index == 0 and step == 10 and sensor_id in deferred_late_seq_by_sensor:
                ctx.proto.datagram_received(
                    _build_sensor_packet(
                        sensor.client_id,
                        sensor.amplitude * 0.95,
                        step,
                        deferred_late_seq_by_sensor.pop(sensor_id),
                        wheel_hz,
                    ),
                    ("127.0.0.1", 7000 + index),
                )
                expected_processed_datagrams += 1
        await _periodic_smoke_flush(
            ctx, step, expected_processed_datagrams, run_id, start_utc, start_mono
        )
    return expected_processed_datagrams


async def _periodic_smoke_flush(
    ctx: _IngestSmokeContext,
    step: int,
    expected_processed_datagrams: int,
    run_id: str,
    start_utc: str,
    start_mono: float,
) -> None:
    if step % 2 == 1:
        await _assert_async_wait_until(
            f"udp processing to reach {expected_processed_datagrams} datagrams",
            lambda expected=expected_processed_datagrams: (
                ctx.ingest_diagnostics.udp_snapshot().processed_datagrams >= expected
            ),
            state=lambda: _backpressure_wait_state(ctx.ingest_diagnostics),
        )
        await _flush_smoke_records(ctx, run_id, start_utc, start_mono)
    if step % 6 == 5:
        await _assert_async_wait_until(
            "udp queue drain after the current burst",
            lambda: ctx.ingest_diagnostics.udp_snapshot().queue_depth == 0,
            state=lambda: _backpressure_wait_state(ctx.ingest_diagnostics),
        )


async def _finish_smoke_load(
    ctx: _IngestSmokeContext,
    expected_processed_datagrams: int,
    run_id: str,
    start_utc: str,
    start_mono: float,
) -> None:
    await _assert_async_wait_until(
        "udp queue drain after simulator load completes",
        lambda expected=expected_processed_datagrams: (
            ctx.ingest_diagnostics.udp_snapshot().queue_depth == 0
            and ctx.ingest_diagnostics.udp_snapshot().processed_datagrams >= expected
        ),
        timeout_s=10.0,
        state=lambda: _backpressure_wait_state(ctx.ingest_diagnostics),
    )
    await _flush_smoke_records(ctx, run_id, start_utc, start_mono)
    await _assert_async_wait_until(
        "raw-capture drain and websocket publish metrics",
        lambda: (
            ctx.ingest_diagnostics.raw_capture_snapshot().queue_depth == 0
            and ctx.ingest_diagnostics.ws_publish_snapshot().total_publish_ticks > 0
        ),
        timeout_s=5.0,
        state=lambda: _backpressure_wait_state(ctx.ingest_diagnostics),
    )


async def _build_smoke_health(ctx: _IngestSmokeContext) -> dict[str, object]:
    return await asyncio.to_thread(
        build_system_health_snapshot,
        ProcessingLoopState(),
        _ready_health_state(),
        ctx.processor,
        ctx.registry,
        ctx.recorder,
        ctx.ingest_diagnostics,
    )


def _assert_smoke_health_contracts(
    health: dict[str, object],
    sensors: list[_SensorSpec],
    expected_processed_datagrams: int,
) -> None:
    ingest = health["ingest"]
    assert isinstance(ingest, dict)
    udp_metrics = ingest["udp"]
    raw_capture_metrics = ingest["raw_capture"]
    ws_metrics = ingest["ws_publish"]
    client_metrics = {row["client_id"]: row for row in ingest["clients"]}
    lead_sensor_metrics = client_metrics[sensors[0].client_id.hex()]

    assert udp_metrics["queue_max_depth"] > 0
    assert udp_metrics["dropped_datagrams"] == 0
    assert udp_metrics["processed_datagrams"] >= expected_processed_datagrams
    assert 0.0 <= udp_metrics["max_packet_queue_age_ms"] <= _MAX_QUEUE_AGE_MS
    assert 0.0 <= udp_metrics["max_ack_latency_ms"] <= _MAX_ACK_LATENCY_MS
    assert raw_capture_metrics["queue_max_depth"] > 0
    assert raw_capture_metrics["dropped_chunks"] == 0
    assert raw_capture_metrics["write_error_chunks"] == 0
    assert ws_metrics["active_connections"] == 1
    assert ws_metrics["total_publish_ticks"] > 0
    assert 0.0 <= ws_metrics["max_publish_duration_ms"] <= _MAX_WS_PUBLISH_MS
    assert health["intake_stats"]["last_ingest_duration_s"] > 0.0
    assert health["intake_stats"]["last_compute_duration_s"] > 0.0
    assert health["intake_stats"]["last_compute_all_duration_s"] > 0.0
    assert set(client_metrics) == {sensor.client_id.hex() for sensor in sensors}
    assert lead_sensor_metrics["frames_dropped"] > 0
    assert lead_sensor_metrics["late_packets"] > 0
    for sensor in sensors:
        row = client_metrics[sensor.client_id.hex()]
        assert row["processed_packets"] > 0
        assert row["processed_samples"] > 0
        assert row["estimated_ingest_hz"] > 0.0


@pytest.mark.asyncio
async def test_ingest_metrics_report_backpressure_contracts_under_bounded_load(
    history_db: HistoryDB,
) -> None:
    ctx = _build_smoke_context(history_db)
    websocket = AsyncMock()
    websocket.send_text = AsyncMock()
    ctx.ws_broadcaster.add(websocket, None)

    tire = TireSpec.from_aspects(
        AnalysisSettingsSnapshot.DEFAULTS,
        deflection_factor=AnalysisSettingsSnapshot.DEFAULTS.get("tire_deflection_factor", 1.0),
    )
    assert tire is not None
    tire_circumference_m = tire.circumference_m

    consumer_task = asyncio.create_task(ctx.proto.process_queue())
    ws_task = asyncio.create_task(ctx.ws_broadcaster.run())
    try:
        started = ctx.recorder.start_recording()
        run_id = started.run_id
        start_utc = started.start_time_utc
        assert run_id is not None
        assert start_utc is not None
        snapshot = ctx.recorder._lifecycle.snapshot()
        assert snapshot is not None
        expected_processed_datagrams = await _drive_bounded_sensor_burst(
            ctx,
            run_id,
            start_utc,
            snapshot.start_mono_s,
            tire_circumference_m,
        )
        await _finish_smoke_load(
            ctx,
            expected_processed_datagrams,
            run_id,
            start_utc,
            snapshot.start_mono_s,
        )
        _assert_smoke_health_contracts(
            await _build_smoke_health(ctx),
            ctx.sensors,
            expected_processed_datagrams,
        )
        await asyncio.to_thread(ctx.recorder.stop_recording)
        assert await asyncio.to_thread(ctx.recorder.post_analysis.wait, timeout_s=30.0)
        stored = await asyncio.to_thread(history_db.get_run, run_id)
        assert stored is not None
        assert stored.raw_capture_manifest is not None
    finally:
        consumer_task.cancel()
        ws_task.cancel()
        with suppress(asyncio.CancelledError):
            await consumer_task
        with suppress(asyncio.CancelledError):
            await ws_task
