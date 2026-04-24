"""Exercise the four-sensor UDP-to-analysis-to-PDF pipeline end to end."""

from __future__ import annotations

import io
import math
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

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
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.shared.constants.units import KMH_TO_MPS
from vibesensor.use_cases.history.report_document import build_report_document
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig

_FRAME_N = 256
_SAMPLE_RATE_HZ = 800
_ACCEL_SCALE = 0.0005

# (client_id_bytes, location, amplitude)
SENSORS: list[tuple[bytes, str, float]] = [
    (bytes.fromhex("020000000001"), "front-left", 1.00),
    (bytes.fromhex("020000000002"), "front-right", 0.58),
    (bytes.fromhex("020000000003"), "rear-left", 0.50),
    (bytes.fromhex("020000000004"), "rear-right", 0.42),
]
_SENSOR_IDS_HEX = {cid.hex() for cid, _, _ in SENSORS}
_SENSOR_LOCATIONS = {loc for _, loc, _ in SENSORS}


class _FakeTransport:
    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        del data, addr


@pytest.fixture
def history_db(tmp_path: Path) -> Iterator[HistoryPersistenceAdapters]:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    yield db
    db.lifecycle.close()


def _register_sensors(registry: ClientRegistry) -> None:
    """Register all test sensors with hello packets and location codes."""
    for client_id, location, _ in SENSORS:
        hello = parse_hello(
            pack_hello(
                client_id,
                control_port=9001,
                sample_rate_hz=_SAMPLE_RATE_HZ,
                name=f"{location}-node",
                frame_samples=_FRAME_N,
                firmware_version="fw-test",
            ),
        )
        registry.update_from_hello(hello, ("127.0.0.1", 9001))
        registry.set_location(client_id.hex(), location)


def _build_sensor_packet(
    client_id: bytes,
    amplitude: float,
    step: int,
    seq: int,
    wheel_hz: float,
) -> bytes:
    """Generate one UDP data packet for the given sensor at the given time step."""
    t = (np.arange(_FRAME_N) + step * _FRAME_N) / _SAMPLE_RATE_HZ
    rng = np.random.default_rng(seed=(step << 8) + int.from_bytes(client_id, "big"))
    sig = (
        amplitude * 0.45 * np.sin(2 * math.pi * wheel_hz * t)
        + amplitude * 0.20 * np.sin(2 * math.pi * (2.0 * wheel_hz) * t + 0.4)
        + 0.04 * rng.normal(size=_FRAME_N)
    )
    raw_x = np.clip(np.round(sig / _ACCEL_SCALE), -32768, 32767).astype(np.int16)
    samples_i16 = np.stack([raw_x, np.zeros_like(raw_x), np.zeros_like(raw_x)], axis=1)
    return pack_data(
        client_id,
        seq=seq,
        t0_us=int((step * _FRAME_N / _SAMPLE_RATE_HZ) * 1_000_000),
        samples=samples_i16,
    )


def test_multi_sensor_udp_to_report_pipeline(
    history_db: HistoryPersistenceAdapters, tmp_path: Path
) -> None:
    """Exercise UDP parse/ingest → processing → recording → analysis → PDF for 4 sensors."""
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

    _register_sensors(registry)

    _tire = TireSpec.from_aspects(
        AnalysisSettingsSnapshot.DEFAULTS,
        deflection_factor=AnalysisSettingsSnapshot.DEFAULTS.get("tire_deflection_factor", 1.0),
    )
    assert _tire is not None
    tire_circ = _tire.circumference_m

    logger.start_recording()
    snapshot = logger._session_snapshot()
    assert snapshot is not None
    run_id = snapshot.run_id
    start_utc = snapshot.start_time_utc
    start_mono = snapshot.start_mono_s
    seq_by_sensor = {client_id.hex(): 1 for client_id, _, _ in SENSORS}

    for step in range(70):
        speed_kmh = (
            20.0 + (80.0 * step / 34.0) if step < 35 else 100.0 - (60.0 * (step - 35) / 34.0)
        )
        gps_monitor.set_speed_override_kmh(speed_kmh)
        wheel_hz = speed_kmh * KMH_TO_MPS / tire_circ
        assert wheel_hz > 0

        for client_id, _, amplitude in SENSORS:
            sensor_id = client_id.hex()
            packet = _build_sensor_packet(
                client_id,
                amplitude,
                step,
                seq_by_sensor[sensor_id],
                wheel_hz,
            )
            proto._process_datagram(packet, ("127.0.0.1", 5005))
            seq_by_sensor[sensor_id] += 1

        active_ids = registry.active_client_ids()
        rates = {
            cid: int(registry.get(cid).sample_rate_hz)
            for cid in active_ids
            if registry.get(cid) is not None
        }
        processor.compute_all(active_ids, sample_rates_hz=rates)
        logger._sample_flush.append_records(
            run_id,
            start_utc,
            start_mono,
        )

    logger.stop_recording()
    assert logger.wait_for_post_analysis(timeout_s=20.0)

    run = history_db.run_repository.get_run(run_id)
    assert run is not None
    assert run.status.value == "complete"
    analysis = run.analysis
    assert analysis is not None

    rows = []
    for batch in history_db.run_repository.iter_run_samples(run_id, batch_size=512):
        rows.extend(batch)
    assert rows
    assert {r.client_id for r in rows} == _SENSOR_IDS_HEX
    assert {r.location for r in rows} == _SENSOR_LOCATIONS
    assert all((r.vibration_strength_db or 0.0) > 0.0 for r in rows[:8])

    front_left_mean_db = np.mean(
        [float(r.vibration_strength_db or 0.0) for r in rows if r.location == "front-left"],
    )
    front_right_mean_db = np.mean(
        [float(r.vibration_strength_db or 0.0) for r in rows if r.location == "front-right"],
    )
    assert front_left_mean_db > front_right_mean_db

    top_causes = analysis.get("top_causes") or []
    assert top_causes
    top = top_causes[0]
    assert "wheel" in str(top.get("suspected_source", "")).lower()
    assert str(top.get("strongest_location")) == "front-left"

    intensity_rows = analysis.get("sensor_intensity_by_location") or []
    by_location = {
        str(row.get("location")): float(row.get("mean_intensity_db", 0.0)) for row in intensity_rows
    }
    assert set(by_location) >= _SENSOR_LOCATIONS
    assert max(by_location, key=by_location.get) == "front-left"
    frame_integrity = {
        str(check.get("check_key")): str(check.get("state"))
        for check in (analysis.get("run_suitability") or [])
        if isinstance(check, dict)
    }
    assert frame_integrity.get("SUITABILITY_CHECK_FRAME_INTEGRITY") == "pass"

    pdf_bytes = build_report_pdf(build_report_document(prepare_report_input(analysis)))
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 1000
    pdf_text = "\n".join(
        filter(None, (page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages)),
    ).lower()
    assert "front-left" in pdf_text
