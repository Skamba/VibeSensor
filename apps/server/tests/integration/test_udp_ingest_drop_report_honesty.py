from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from test_support.findings import make_finding_payload
from test_support.history_db_lifecycle import build_history_db
from test_support.report_helpers import minimal_summary

from vibesensor.adapters.gps.gps_speed import SpeedResolution
from vibesensor.adapters.udp.protocol import HelloMessage, pack_data
from vibesensor.adapters.udp.udp_data_rx import DataDatagramProtocol
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.runtime.registry import ClientRegistry
from vibesensor.shared.boundaries.reporting import prepare_persisted_report_input
from vibesensor.shared.boundaries.runs.metadata import run_metadata_to_json_object
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.run_context_warning import WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS
from vibesensor.shared.types.aligned_speed_context import AlignedSpeedContextSnapshot
from vibesensor.use_cases.history.report_document import build_report_document
from vibesensor.use_cases.run import RunRecorder, RunRecorderConfig
from vibesensor.use_cases.run.post_analysis_input import build_post_analysis_input
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary

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


def _samples() -> np.ndarray:
    time_axis = np.arange(256, dtype=np.float64) / 800.0
    wave = np.round(1200.0 * np.sin(2.0 * np.pi * 40.0 * time_axis)).astype(np.int16)
    zeros = np.zeros(256, dtype=np.int16)
    return np.column_stack([wave, zeros, zeros])


def test_udp_ingest_queue_drop_reaches_persisted_report_honesty(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = build_history_db(tmp_path)
    try:
        registry = ClientRegistry(db=history_db.client_name_repository)
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
            history_db=history_db.run_repository,
            language_reader=SimpleNamespace(language="en"),
        )
        proto = DataDatagramProtocol(
            registry=registry,
            processor=processor,
            raw_capture_sink=recorder,
            queue_maxsize=1,
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
        snapshot = recorder._session_snapshot()
        assert snapshot is not None
        run_id = snapshot.run_id

        first = pack_data(_CLIENT_ID, seq=1, t0_us=0, samples=_samples())
        dropped = pack_data(_CLIENT_ID, seq=2, t0_us=320_000, samples=_samples())
        proto.datagram_received(first, _ADDR)
        proto.datagram_received(dropped, _ADDR)

        queued_data, queued_addr, _received_mono_s = proto._queue.get_nowait()
        try:
            proto._process_datagram(queued_data, queued_addr)
        finally:
            proto._queue.task_done()

        monkeypatch.setattr(recorder, "schedule_post_analysis", lambda _run_id: None)
        recorder.stop_recording()
        recorder.shutdown_raw_capture()

        stored = history_db.run_repository.get_run(run_id)
        assert stored is not None
        assert stored.raw_capture_manifest is not None
        manifest = stored.raw_capture_manifest
        assert manifest.losses.udp_ingest_queue_drop_count == 1
        assert manifest.total_dropped_chunk_count == 1
        sensor_loss = manifest.sensor_loss(_CLIENT_ID_HEX)
        assert sensor_loss is not None
        assert sensor_loss.losses.udp_ingest_queue_drop_count == 1

        raw_capture = history_db.run_repository._run_sync(
            history_db.run_repository.aload_raw_capture(run_id)
        )
        assert raw_capture is not None

        finding = make_finding_payload(
            finding_id="F_INGEST_DROP",
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
                    diagnostic_case=SimpleNamespace(case_id="case-ingest-drop"),
                )

        monkeypatch.setattr(
            "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
            FakeRunAnalysis,
        )
        monkeypatch.setattr(
            "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
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

        assert summary["analysis_metadata"]["raw_replay_udp_ingest_queue_drop_count"] == 1
        assert WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS in [
            warning["code"] for warning in summary["warnings"]
        ]

        prepared = prepare_persisted_report_input(summary)
        document = build_report_document(prepared)

        assert any("UDP ingest queue drops" in (row.detail or "") for row in document.data_trust)
    finally:
        history_db.lifecycle.close()


def test_clean_udp_run_keeps_report_free_of_ingest_drop_warning(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_db = build_history_db(tmp_path)
    try:
        registry = ClientRegistry(db=history_db.client_name_repository)
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
            history_db=history_db.run_repository,
            language_reader=SimpleNamespace(language="en"),
        )
        proto = DataDatagramProtocol(
            registry=registry,
            processor=processor,
            raw_capture_sink=recorder,
            queue_maxsize=4,
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
        snapshot = recorder._session_snapshot()
        assert snapshot is not None
        run_id = snapshot.run_id

        packet = pack_data(_CLIENT_ID, seq=1, t0_us=0, samples=_samples())
        proto.datagram_received(packet, _ADDR)
        queued_data, queued_addr, _received_mono_s = proto._queue.get_nowait()
        try:
            proto._process_datagram(queued_data, queued_addr)
        finally:
            proto._queue.task_done()

        monkeypatch.setattr(recorder, "schedule_post_analysis", lambda _run_id: None)
        recorder.stop_recording()
        recorder.shutdown_raw_capture()

        stored = history_db.run_repository.get_run(run_id)
        assert stored is not None
        assert stored.raw_capture_manifest is not None
        manifest = stored.raw_capture_manifest
        assert manifest.losses.udp_ingest_queue_drop_count == 0
        assert manifest.total_dropped_chunk_count == 0
        assert manifest.sensor_loss(_CLIENT_ID_HEX) is None

        raw_capture = history_db.run_repository._run_sync(
            history_db.run_repository.aload_raw_capture(run_id)
        )
        assert raw_capture is not None

        finding = make_finding_payload(
            finding_id="F_CLEAN_RUN",
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
                    diagnostic_case=SimpleNamespace(case_id="case-clean-run"),
                )

        monkeypatch.setattr(
            "vibesensor.use_cases.diagnostics.run_analysis.RunAnalysis",
            FakeRunAnalysis,
        )
        monkeypatch.setattr(
            "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
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
                                "t_s": 0.0,
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

        assert summary["analysis_metadata"]["raw_replay_udp_ingest_queue_drop_count"] == 0
        assert WARNING_CODE_RAW_REPLAY_DROPPED_CHUNKS not in [
            warning["code"] for warning in summary.get("warnings", [])
        ]

        prepared = prepare_persisted_report_input(summary)
        document = build_report_document(prepared)

        assert not any(
            "UDP ingest queue drops" in (row.detail or "") for row in document.data_trust
        )
    finally:
        history_db.lifecycle.close()
