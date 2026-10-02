from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_support.findings import make_finding_payload
from test_support.history_db_lifecycle import build_history_db
from test_support.report_helpers import minimal_summary

from vibesensor.analysis.post_analysis_input import build_post_analysis_input
from vibesensor.analysis.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.analysis.post_analysis_summary import build_post_analysis_summary
from vibesensor.ingest.protocol import HelloMessage, pack_data
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.udp_data_rx import DataDatagramProtocol
from vibesensor.live.processor import SignalProcessor
from vibesensor.recording._recorder_types import RunRecorderConfig
from vibesensor.recording.recorder import RunRecorder
from vibesensor.recording.run_metadata import run_metadata_to_json_object
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.report.document.builder import build_report_document
from vibesensor.report.preparation import prepare_persisted_report_input
from vibesensor.speed.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.speed.gps_speed import SpeedResolution
from vibesensor.summary.run_context_warning import WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS

_CLIENT_ID = bytes.fromhex("010203040506")
_CLIENT_ID_HEX = _CLIENT_ID.hex()
_ADDR = ("127.0.0.1", 12345)


class _FakeTransport:
    def sendto(self, _data: bytes, _addr: tuple[str, int]) -> None:
        return None


class _FakeSpeedProvider:
    gps_speed_mps: float | None = None
    engine_rpm: float | None = None
    engine_rpm_source: str | None = None

    def resolve_speed(self) -> SpeedResolution:
        return SpeedResolution(speed_mps=None, fallback_active=False, source="none")

    def resolve_speed_context_at(
        self,
        _target_mono_s: float | None,
        *,
        tolerance_s: float | None = None,
    ) -> AlignedSpeedContextSnapshot:
        del tolerance_s
        return AlignedSpeedContextSnapshot(
            selected_speed_source="gps",
            resolved_speed_mps=None,
            resolved_speed_source="none",
            resolved_speed_aligned=False,
            gps_speed_mps=None,
            gps_speed_aligned=False,
            measured_engine_rpm=None,
            measured_engine_rpm_source=None,
            measured_engine_rpm_aligned=False,
        )


def _processor() -> SignalProcessor:
    return SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=100,
        fft_n=256,
        spectrum_max_hz=200,
        accel_scale_g_per_lsb=0.0005,
    )


def _samples(freq_hz: float) -> np.ndarray:
    time_axis = np.arange(256, dtype=np.float64) / 800.0
    wave = np.round(1200.0 * np.sin(2.0 * np.pi * freq_hz * time_axis)).astype(np.int16)
    zeros = np.zeros(256, dtype=np.int16)
    return np.column_stack([wave, zeros, zeros])


def test_late_udp_packet_reaches_persisted_report_honesty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = build_history_db(tmp_path)
    try:
        registry = ClientRegistry(db=history_db)
        processor = _processor()
        recorder = RunRecorder(
            RunRecorderConfig(
                metrics_log_hz=20,
                sensor_model="ADXL345",
                default_sample_rate_hz=800,
                fft_window_size_samples=256,
                persist_history_db=True,
            ),
            registry=registry,
            gps_monitor=_FakeSpeedProvider(),
            processor=processor,
            history_db=history_db,
            language_reader=SimpleNamespace(language="en"),
        )
        proto = DataDatagramProtocol(
            registry=registry,
            processor=processor,
            raw_capture_sink=recorder.raw_capture,
            queue_maxsize=8,
        )
        proto.connection_made(_FakeTransport())
        registry.update_from_hello(
            HelloMessage(
                client_id=_CLIENT_ID,
                control_port=9010,
                sample_rate_hz=800,
                name="sensor-a",
                firmware_version="fw",
            ),
            _ADDR,
            now=1.0,
        )
        registry.set_location(_CLIENT_ID_HEX, "front-left")

        recorder.start_recording()
        snapshot = recorder._lifecycle.snapshot()
        assert snapshot is not None
        run_id = snapshot.run_id

        first = pack_data(_CLIENT_ID, seq=0, t0_us=1_000_000, samples=_samples(40.0))
        newest = pack_data(_CLIENT_ID, seq=2, t0_us=1_640_000, samples=_samples(55.0))
        late = pack_data(_CLIENT_ID, seq=1, t0_us=1_320_000, samples=_samples(25.0))

        proto._process_datagram(first, _ADDR)
        proto._process_datagram(newest, _ADDR)
        proto._process_datagram(late, _ADDR)

        monkeypatch.setattr(recorder.post_analysis, "schedule", lambda _run_id: None)
        recorder.stop_recording()
        recorder.raw_capture.shutdown()

        stored = history_db.get_run(run_id)
        assert stored is not None
        assert stored.raw_capture_manifest is not None
        manifest = stored.raw_capture_manifest
        assert manifest.losses.late_packet_chunk_count == 1
        assert manifest.total_late_packet_chunk_count == 1
        sensor_loss = manifest.sensor_loss(_CLIENT_ID_HEX)
        assert sensor_loss is not None
        assert sensor_loss.losses.late_packet_chunk_count == 1

        raw_capture = history_db.load_raw_capture(run_id)
        assert raw_capture is not None

        finding = make_finding_payload(
            finding_id="F_LATE_PACKET",
            suspected_source="wheel/tire",
            confidence=0.75,
            strongest_location="Front Left",
            strongest_speed_band="40-60 km/h",
        )

        class FakeRunAnalysis:
            def __init__(self, *_args, **_kwargs):
                pass

            def summarize(self):
                return SimpleNamespace(
                    diagnostic_case=SimpleNamespace(case_id="case-late-packet"),
                )

        monkeypatch.setattr(
            "vibesensor.analysis.run_analysis.RunAnalysis",
            FakeRunAnalysis,
        )
        monkeypatch.setattr(
            "vibesensor.analysis.post_analysis_summary.analysis_result_to_summary",
            lambda _result: minimal_summary(
                run_id=run_id,
                lang="en",
                metadata=run_metadata_to_json_object(stored.metadata),
                findings=[finding],
                top_causes=[finding],
                sensor_count_used=1,
                sensor_locations=["Front Left"],
                sensor_locations_connected_throughout=["Front Left"],
            ),
        )

        summary = build_post_analysis_summary(
            build_post_analysis_input(
                LoadedPostAnalysisRun(
                    run_id=run_id,
                    metadata=stored.metadata,
                    language="en",
                    samples=sensor_frames_from_mappings(
                        [
                            {
                                "client_id": _CLIENT_ID_HEX,
                                "client_name": "Front Left",
                                "t_s": 0.32,
                                "sample_rate_hz": 800,
                                "vibration_strength_db": 12.0,
                                "dominant_freq_hz": 40.0,
                            }
                        ]
                    ),
                    raw_capture=raw_capture,
                    total_summary_row_count=1,
                    stride=1,
                )
            )
        )

        assert summary["analysis_metadata"]["raw_replay_late_packet_chunk_count"] == 1
        assert WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS in [
            warning["code"] for warning in summary["warnings"]
        ]

        prepared = prepare_persisted_report_input(summary)
        document = build_report_document(prepared)

        late_packet_rows = [
            row
            for row in document.data_trust
            if "late or out-of-order packets quarantined from live processing" in (row.detail or "")
        ]
        assert late_packet_rows
        assert late_packet_rows[0].state == "warn"
    finally:
        history_db.close()
