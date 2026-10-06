"""Exercise end-to-end sensor failure handling across ingest, analysis, and PDF prep."""

from __future__ import annotations

import io
import math
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import anyio
import numpy as np
import pytest
from pypdf import PdfReader
from test_support.core import TEST_CAR_ASPECTS
from test_support.power import unknown_power
from test_support.speed import observed_speed

from vibesensor.common.units import KMH_TO_MPS
from vibesensor.domain.tire_spec import TireSpec
from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.ingest.protocol_packing import pack_data, pack_hello
from vibesensor.ingest.protocol_parsing import parse_hello
from vibesensor.ingest.registry import STREAM_START_GRACE_S, ClientRegistry
from vibesensor.ingest.udp_data_rx import DataDatagramProtocol
from vibesensor.live.processing_loop import ProcessingLoopState, ProcessingTickRunner
from vibesensor.live.processor import SignalProcessor
from vibesensor.recording._recorder_types import RunRecorderConfig
from vibesensor.recording.recorder import RunRecorder
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.view_model import QualityCheck, ReportView, build_report_view
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.web.health_snapshot import build_system_health_snapshot
from vibesensor.web.health_state import RuntimeHealthState

_FRAME_N = 256
_SAMPLE_RATE_HZ = 800
_ACCEL_SCALE = 0.0005
_STEPS = 70


@dataclass(frozen=True, slots=True)
class _SensorConfig:
    client_id: bytes
    location: str
    amplitude: float
    advertised_sample_rate_hz: int = _SAMPLE_RATE_HZ
    signal_sample_rate_hz: int = _SAMPLE_RATE_HZ
    frame_samples: int = _FRAME_N
    queue_overflow_drops: int = 0


@dataclass(frozen=True, slots=True)
class _PipelineArtifacts:
    analysis: dict[str, object]
    health: dict[str, object]
    pdf_bytes: bytes
    pdf_text: str
    report_view: ReportView


type _BeforeStepHook = Callable[[int, ClientRegistry, dict[str, int]], None]


SENSORS: tuple[_SensorConfig, ...] = (
    _SensorConfig(bytes.fromhex("020000000001"), "front-left", 1.00),
    _SensorConfig(bytes.fromhex("020000000002"), "front-right", 0.58),
    _SensorConfig(bytes.fromhex("020000000003"), "rear-left", 0.50),
    _SensorConfig(bytes.fromhex("020000000004"), "rear-right", 0.42),
)


class _FakeTransport:
    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        del data, addr


@pytest.fixture
def history_db(tmp_path: Path) -> Iterator[HistoryDB]:
    db = HistoryDB(tmp_path / "history.db")
    yield db
    db.close()


def _register_sensor(
    registry: ClientRegistry,
    sensor: _SensorConfig,
    *,
    now_mono: float | None = None,
) -> None:
    hello = parse_hello(
        pack_hello(
            sensor.client_id,
            control_port=9001,
            sample_rate_hz=sensor.advertised_sample_rate_hz,
            name=f"{sensor.location}-node",
            frame_samples=sensor.frame_samples,
            firmware_version="fw-test",
            queue_overflow_drops=sensor.queue_overflow_drops,
        ),
    )
    registry.update_from_hello(hello, ("127.0.0.1", 9001), now_mono=now_mono)
    registry.set_location(sensor.client_id.hex(), sensor.location)


def _build_sensor_packet(
    sensor: _SensorConfig,
    *,
    step: int,
    seq: int,
    wheel_hz: float,
) -> bytes:
    sample_rate_hz = float(sensor.signal_sample_rate_hz)
    t = (np.arange(_FRAME_N) + step * _FRAME_N) / sample_rate_hz
    rng = np.random.default_rng(seed=(step << 8) + int.from_bytes(sensor.client_id, "big"))
    sig = (
        sensor.amplitude * 0.45 * np.sin(2 * math.pi * wheel_hz * t)
        + sensor.amplitude * 0.20 * np.sin(2 * math.pi * (2.0 * wheel_hz) * t + 0.4)
        + 0.04 * rng.normal(size=_FRAME_N)
    )
    raw_x = np.clip(np.round(sig / _ACCEL_SCALE), -32768, 32767).astype(np.int16)
    samples_i16 = np.stack([raw_x, np.zeros_like(raw_x), np.zeros_like(raw_x)], axis=1)
    return pack_data(
        sensor.client_id,
        seq=seq,
        t0_us=int((step * _FRAME_N / sample_rate_hz) * 1_000_000),
        samples=samples_i16,
    )


def _build_pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(
        filter(None, (page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages)),
    ).lower()


def _ready_health_state() -> RuntimeHealthState:
    health_state = RuntimeHealthState()
    health_state.mark_ready()
    return health_state


def _run_tick(runner: ProcessingTickRunner) -> int:
    return anyio.run(lambda: runner.run(sync_clock=False))


def _run_suitability_state(analysis: dict[str, object], check_key: str) -> str | None:
    for raw_check in analysis.get("run_suitability") or []:
        if isinstance(raw_check, dict) and raw_check.get("check_key") == check_key:
            state = raw_check.get("state")
            return str(state) if isinstance(state, str) else None
    return None


def _quality_check(report_view: ReportView, label: str) -> QualityCheck:
    for check in report_view.quality.checks:
        if check.label == label:
            return check
    raise AssertionError(f"Missing data-quality check {label!r}")


def _run_pipeline(
    history_db: HistoryDB,
    *,
    sensors: tuple[_SensorConfig, ...] = SENSORS,
    before_step: _BeforeStepHook | None = None,
) -> _PipelineArtifacts:
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
    logger = RunRecorder(
        RunRecorderConfig(
            metrics_log_hz=20,
            sensor_model="ADXL345",
            default_sample_rate_hz=_SAMPLE_RATE_HZ,
            fft_window_size_samples=_FRAME_N,
            persist_history_db=True,
        ),
        registry=registry,
        gps_monitor=observed_speed(gps_monitor),
        processor=processor,
        history_db=history_db,
        ui_preferences=SimpleNamespace(language="en", time_zone=None),
    )
    proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=256)
    proto.connection_made(_FakeTransport())
    loop_state = ProcessingLoopState()
    tick_runner = ProcessingTickRunner(
        state=loop_state,
        sample_rate_hz=_SAMPLE_RATE_HZ,
        fft_n=_FRAME_N,
        registry=registry,
        processor=processor,
    )

    for sensor in sensors:
        _register_sensor(registry, sensor)

    tire = TireSpec.from_aspects(
        TEST_CAR_ASPECTS, deflection_factor=TEST_CAR_ASPECTS["tire_deflection_factor"]
    )
    assert tire is not None
    tire_circ = tire.circumference_m

    logger.start_recording()
    snapshot = logger._lifecycle.snapshot()
    assert snapshot is not None
    run_id = snapshot.run_id
    start_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    seq_by_sensor = {sensor.client_id.hex(): 1 for sensor in sensors}

    for step in range(_STEPS):
        if before_step is not None:
            before_step(step, registry, seq_by_sensor)
        if step < 35:
            speed_kmh = 20.0 + (80.0 * step / 34.0)
        else:
            speed_kmh = 100.0 - (60.0 * (step - 35) / 34.0)
        gps_monitor.set_speed_override_kmh(speed_kmh)
        wheel_hz = speed_kmh * KMH_TO_MPS / tire_circ
        assert wheel_hz > 0

        for sensor in sensors:
            sensor_id = sensor.client_id.hex()
            packet = _build_sensor_packet(
                sensor,
                step=step,
                seq=seq_by_sensor[sensor_id],
                wheel_hz=wheel_hz,
            )
            proto._process_datagram(packet, ("127.0.0.1", 5005))
            seq_by_sensor[sensor_id] += 1

        _run_tick(tick_runner)
        logger._sample_flush.append_records(run_id, start_utc, start_mono)

    logger.stop_recording()
    assert logger.post_analysis.wait(timeout_s=20.0)

    run = history_db.get_run(run_id)
    assert run is not None
    assert run.status.value == "complete"
    analysis = run.analysis
    assert analysis is not None

    report_view = build_report_view(analysis.payload, run.metadata)
    pdf_bytes = render_report_pdf(report_view)
    health = build_system_health_snapshot(
        loop_state,
        _ready_health_state(),
        processor,
        registry,
        logger,
        IngestDiagnosticsCollector(),
        "",
        unknown_power(),
    )
    return _PipelineArtifacts(
        analysis=analysis,
        health=health,
        pdf_bytes=pdf_bytes,
        pdf_text=_build_pdf_text(pdf_bytes),
        report_view=report_view,
    )


def test_sensor_queue_overflow_counter_reaches_report_data_trust(
    history_db: HistoryDB,
) -> None:
    overflow_sensor = next(sensor for sensor in SENSORS if sensor.location == "front-right")

    def _before_step(step: int, registry: ClientRegistry, _seq_by_sensor: dict[str, int]) -> None:
        # Mid-run HELLOs, after the stream's startup grace.
        mid_run_mono = time.monotonic() + STREAM_START_GRACE_S
        if step == 24:
            _register_sensor(
                registry, replace(overflow_sensor, queue_overflow_drops=3), now_mono=mid_run_mono
            )
        if step == 48:
            _register_sensor(
                registry, replace(overflow_sensor, queue_overflow_drops=7), now_mono=mid_run_mono
            )

    artifacts = _run_pipeline(history_db, before_step=_before_step)

    assert artifacts.health["status"] == "warn"
    assert artifacts.health["data_loss"]["queue_overflow_drops"] == 7
    assert "queue_overflow_drops" in artifacts.health["degradation_reasons"]
    assert (
        _run_suitability_state(
            artifacts.analysis,
            "SUITABILITY_CHECK_FRAME_INTEGRITY",
        )
        == "warn"
    )
    frame_integrity = _quality_check(artifacts.report_view, "Frame integrity")
    assert not frame_integrity.passed
    assert "0 dropped frames" in frame_integrity.detail
    assert "7 queue overflows" in frame_integrity.detail
    assert "front-left" in artifacts.pdf_text


def test_overflow_from_before_a_server_restart_is_no_warning_and_no_run_loss(
    history_db: HistoryDB,
) -> None:
    """A sensor streams on through a server update; its queue overflowed meanwhile."""
    overflow_sensor = next(sensor for sensor in SENSORS if sensor.location == "front-right")
    sensors = tuple(
        replace(sensor, queue_overflow_drops=31) if sensor is overflow_sensor else sensor
        for sensor in SENSORS
    )

    def _before_step(step: int, registry: ClientRegistry, _seq_by_sensor: dict[str, int]) -> None:
        if step == 2:
            # Its next HELLO: one more drop while its backlog drained.
            _register_sensor(registry, replace(overflow_sensor, queue_overflow_drops=32))

    artifacts = _run_pipeline(history_db, sensors=sensors, before_step=_before_step)

    assert artifacts.health["status"] == "ok"
    assert artifacts.health["recent_data_loss"]["queue_overflow_drops"] == 0
    assert artifacts.health["data_loss"]["queue_overflow_drops"] == 32
    assert _run_suitability_state(artifacts.analysis, "SUITABILITY_CHECK_FRAME_INTEGRITY") == "pass"
    assert _quality_check(artifacts.report_view, "Frame integrity").passed
