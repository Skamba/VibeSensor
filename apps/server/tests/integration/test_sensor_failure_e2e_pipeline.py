"""Exercise end-to-end sensor failure handling across ingest, analysis, and PDF prep."""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import anyio
import numpy as np
import pytest
from pypdf import PdfReader

from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
from vibesensor.adapters.pdf.pdf_engine import build_report_pdf
from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)
from vibesensor.adapters.udp.protocol import pack_data, pack_hello, parse_hello
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol
from vibesensor.domain import TireSpec
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.health_snapshot import build_system_health_snapshot
from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.processing_state import ProcessingLoopState
from vibesensor.infra.runtime.processing_tick import ProcessingTickRunner
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.constants.units import KMH_TO_MPS
from vibesensor.use_cases.history.report_document import build_report_document
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig

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
    report_document: object


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
def history_db(tmp_path: Path) -> Iterator[HistoryPersistenceAdapters]:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    yield db
    db.lifecycle.close()


def _register_sensor(registry: ClientRegistry, sensor: _SensorConfig) -> None:
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
    registry.update_from_hello(hello, ("127.0.0.1", 9001))
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


def _data_trust_row(report_document: object, check: str):
    rows = getattr(report_document, "data_trust", ())
    for row in rows:
        if getattr(row, "check", None) == check:
            return row
    raise AssertionError(f"Missing data-trust row for {check!r}")


def _run_pipeline(
    history_db: HistoryPersistenceAdapters,
    *,
    sensors: tuple[_SensorConfig, ...] = SENSORS,
    before_step: _BeforeStepHook | None = None,
) -> _PipelineArtifacts:
    registry = ClientRegistry(db=history_db.client_name_repository)
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
        gps_monitor=gps_monitor,
        processor=processor,
        history_db=history_db.run_repository,
        language_reader=SimpleNamespace(language="en"),
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
        AnalysisSettingsSnapshot.DEFAULTS,
        deflection_factor=AnalysisSettingsSnapshot.DEFAULTS.get("tire_deflection_factor", 1.0),
    )
    assert tire is not None
    tire_circ = tire.circumference_m

    logger.start_recording()
    snapshot = logger._session_snapshot()
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
    assert logger.wait_for_post_analysis(timeout_s=20.0)

    run = history_db.run_repository.get_run(run_id)
    assert run is not None
    assert run.status.value == "complete"
    analysis = run.analysis
    assert analysis is not None

    report_document = build_report_document(prepare_report_input(analysis))
    pdf_bytes = build_report_pdf(report_document)
    health = build_system_health_snapshot(
        loop_state,
        _ready_health_state(),
        processor,
        registry,
        logger,
    )
    return _PipelineArtifacts(
        analysis=analysis,
        health=health,
        pdf_bytes=pdf_bytes,
        pdf_text=_build_pdf_text(pdf_bytes),
        report_document=report_document,
    )


def test_sample_rate_mismatch_warns_in_health_but_pipeline_completes(
    history_db: HistoryPersistenceAdapters,
) -> None:
    sensors = tuple(
        replace(
            sensor,
            advertised_sample_rate_hz=400,
            signal_sample_rate_hz=400,
        )
        if sensor.location == "rear-right"
        else sensor
        for sensor in SENSORS
    )

    artifacts = _run_pipeline(history_db, sensors=sensors)

    top_causes = artifacts.analysis.get("top_causes") or []
    assert top_causes
    assert str(top_causes[0].get("strongest_location")) == "front-left"
    assert artifacts.health["status"] == "warn"
    assert artifacts.health["sample_rate_mismatch_count"] == 1
    assert "sample_rate_mismatch" in artifacts.health["degradation_reasons"]
    assert artifacts.health["data_loss"]["frames_dropped"] == 0
    assert artifacts.pdf_bytes.startswith(b"%PDF-")
    assert "front-left" in artifacts.pdf_text


def test_dropped_frames_surface_in_health_and_report_data_trust(
    history_db: HistoryPersistenceAdapters,
) -> None:
    glitched_sensor = next(sensor for sensor in SENSORS if sensor.location == "rear-right")

    def _before_step(step: int, _registry: ClientRegistry, seq_by_sensor: dict[str, int]) -> None:
        if step in {18, 42}:
            seq_by_sensor[glitched_sensor.client_id.hex()] += 2

    artifacts = _run_pipeline(history_db, before_step=_before_step)

    assert artifacts.health["status"] == "warn"
    assert artifacts.health["data_loss"]["frames_dropped"] == 4
    assert "frames_dropped" in artifacts.health["degradation_reasons"]
    assert (
        _run_suitability_state(
            artifacts.analysis,
            "SUITABILITY_CHECK_FRAME_INTEGRITY",
        )
        == "warn"
    )
    frame_integrity = _data_trust_row(artifacts.report_document, "Frame integrity")
    assert frame_integrity.state == "warn"
    assert "4 dropped frames" in (frame_integrity.detail or "")
    assert "0 queue overflows" in (frame_integrity.detail or "")
    assert "front-left" in artifacts.pdf_text


def test_sensor_queue_overflow_counter_reaches_report_data_trust(
    history_db: HistoryPersistenceAdapters,
) -> None:
    overflow_sensor = next(sensor for sensor in SENSORS if sensor.location == "front-right")

    def _before_step(step: int, registry: ClientRegistry, _seq_by_sensor: dict[str, int]) -> None:
        if step == 24:
            _register_sensor(registry, replace(overflow_sensor, queue_overflow_drops=3))
        if step == 48:
            _register_sensor(registry, replace(overflow_sensor, queue_overflow_drops=7))

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
    frame_integrity = _data_trust_row(artifacts.report_document, "Frame integrity")
    assert frame_integrity.state == "warn"
    assert "0 dropped frames" in (frame_integrity.detail or "")
    assert "7 queue overflows" in (frame_integrity.detail or "")
    assert "front-left" in artifacts.pdf_text
