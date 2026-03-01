from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from pypdf import PdfReader

from vibesensor.analysis import map_summary
from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettingsStore,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from vibesensor.gps_speed import GPSSpeedMonitor
from vibesensor.history_db import HistoryDB
from vibesensor.metrics_log import MetricsLogger
from vibesensor.processing import SignalProcessor
from vibesensor.protocol import pack_data, pack_hello, parse_hello
from vibesensor.registry import ClientRegistry
from vibesensor.report.pdf_builder import build_report_pdf
from vibesensor.udp_data_rx import DataDatagramProtocol


class _FakeTransport:
    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        del data, addr


def test_multi_sensor_udp_to_report_pipeline(tmp_path: Path) -> None:
    """Exercise UDP parse/ingest → processing → recording → analysis → PDF for 4 sensors."""
    db = HistoryDB(tmp_path / "history.db")
    try:
        registry = ClientRegistry(db=db)
        processor = SignalProcessor(
            sample_rate_hz=800,
            waveform_seconds=4,
            waveform_display_hz=100,
            fft_n=256,
            spectrum_max_hz=200,
            accel_scale_g_per_lsb=0.0005,
        )
        gps_monitor = GPSSpeedMonitor(gps_enabled=False)
        settings_store = AnalysisSettingsStore()
        logger = MetricsLogger(
            enabled=False,
            log_path=tmp_path / "metrics.jsonl",
            metrics_log_hz=20,
            registry=registry,
            gps_monitor=gps_monitor,
            processor=processor,
            analysis_settings=settings_store,
            sensor_model="ADXL345",
            default_sample_rate_hz=800,
            fft_window_size_samples=256,
            history_db=db,
            persist_history_db=True,
            language_provider=lambda: "en",
        )
        proto = DataDatagramProtocol(registry=registry, processor=processor, queue_maxsize=256)
        proto.connection_made(_FakeTransport())

        sensors: list[tuple[bytes, str, float]] = [
            (bytes.fromhex("020000000001"), "front-left", 1.00),
            (bytes.fromhex("020000000002"), "front-right", 0.58),
            (bytes.fromhex("020000000003"), "rear-left", 0.50),
            (bytes.fromhex("020000000004"), "rear-right", 0.42),
        ]
        for client_id, location, _ in sensors:
            hello = parse_hello(
                pack_hello(
                    client_id,
                    control_port=9001,
                    sample_rate_hz=800,
                    name=f"{location}-node",
                    frame_samples=256,
                    firmware_version="fw-test",
                )
            )
            registry.update_from_hello(hello, ("127.0.0.1", 9001))
            registry.set_location(client_id.hex(), location)

        tire_circ = tire_circumference_m_from_spec(
            DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"],
            DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"],
            DEFAULT_ANALYSIS_SETTINGS["rim_in"],
            deflection_factor=DEFAULT_ANALYSIS_SETTINGS.get("tire_deflection_factor"),
        )
        assert tire_circ is not None

        logger.start_logging()
        run_id = str(logger._run_id)
        start_utc = str(logger._run_start_utc)
        start_mono = float(logger._run_start_mono_s)
        seq = 1
        frame_n = 256
        sample_rate = 800.0

        for step in range(70):
            speed_kmh = (
                20.0 + (80.0 * step / 34.0) if step < 35 else 100.0 - (60.0 * (step - 35) / 34.0)
            )
            gps_monitor.set_speed_override_kmh(speed_kmh)
            wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, tire_circ)
            assert wheel_hz is not None and wheel_hz > 0
            t = (np.arange(frame_n) + step * frame_n) / sample_rate

            for client_id, _, amplitude in sensors:
                rng = np.random.default_rng(seed=(step << 8) + int.from_bytes(client_id, "big"))
                sig = (
                    amplitude * 0.45 * np.sin(2 * math.pi * wheel_hz * t)
                    + amplitude * 0.20 * np.sin(2 * math.pi * (2.0 * wheel_hz) * t + 0.4)
                    + 0.04 * rng.normal(size=frame_n)
                )
                raw_x = np.clip(np.round(sig / 0.0005), -32768, 32767).astype(np.int16)
                samples_i16 = np.stack(
                    [raw_x, np.zeros_like(raw_x), np.zeros_like(raw_x)],
                    axis=1,
                )
                packet = pack_data(
                    client_id,
                    seq=seq,
                    t0_us=int((step * frame_n / sample_rate) * 1_000_000),
                    samples=samples_i16,
                )
                proto._process_datagram(packet, ("127.0.0.1", 5005))
                seq += 1

            active_ids = registry.active_client_ids()
            rates = {
                cid: int(registry.get(cid).sample_rate_hz)
                for cid in active_ids
                if registry.get(cid) is not None
            }
            metrics_by_client = processor.compute_all(active_ids, sample_rates_hz=rates)
            for cid, metrics in metrics_by_client.items():
                registry.set_latest_metrics(cid, metrics)
            logger._append_records(
                run_id,
                start_utc,
                start_mono,
                session_generation=logger._session_generation,
            )

        logger.stop_logging()
        assert logger.wait_for_post_analysis(timeout_s=20.0)

        run = db.get_run(run_id)
        assert run is not None
        assert run["status"] == "complete"
        analysis = run.get("analysis")
        assert isinstance(analysis, dict)

        rows: list[dict[str, object]] = []
        for batch in db.iter_run_samples(run_id, batch_size=512):
            rows.extend(batch)
        assert rows
        assert {str(r["client_id"]) for r in rows} == {cid.hex() for cid, _, _ in sensors}
        assert {str(r["location"]) for r in rows} == {loc for _, loc, _ in sensors}
        assert all(float(r.get("vibration_strength_db", 0.0)) > 0.0 for r in rows[:8])

        front_left_mean_db = np.mean(
            [float(r["vibration_strength_db"]) for r in rows if r["location"] == "front-left"]
        )
        front_right_mean_db = np.mean(
            [float(r["vibration_strength_db"]) for r in rows if r["location"] == "front-right"]
        )
        assert front_left_mean_db > front_right_mean_db

        top_causes = analysis.get("top_causes") or []
        assert top_causes
        top = top_causes[0]
        assert "wheel" in str(top.get("source", "")).lower()
        assert str(top.get("strongest_location")) == "front-left"

        intensity_rows = analysis.get("sensor_intensity_by_location") or []
        by_location = {
            str(row.get("location")): float(row.get("mean_intensity_db", 0.0))
            for row in intensity_rows
        }
        assert set(by_location) >= {loc for _, loc, _ in sensors}
        assert max(by_location, key=by_location.get) == "front-left"

        pdf_bytes = build_report_pdf(map_summary(analysis))
        assert pdf_bytes.startswith(b"%PDF-")
        assert len(pdf_bytes) > 1000
        pdf_text = "\n".join(
            filter(None, (page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages))
        ).lower()
        assert "front-left" in pdf_text
    finally:
        db.close()
