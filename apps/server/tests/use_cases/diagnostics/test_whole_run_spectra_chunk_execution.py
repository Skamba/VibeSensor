from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import numpy as np
import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics import whole_run_spectra as spectra


def _metadata() -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": "run-spectra",
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 8,
            "sample_rate_hz": 8,
            "feature_interval_s": 0.5,
            "fft_window_size_samples": 8,
            "accel_scale_g_per_lsb": 0.001,
        }
    )


def _chunk(sensor_id: str, chunk_index: int) -> spectra._SpectralChunk:
    return spectra._SpectralChunk(
        sensor_data=SimpleNamespace(manifest=SimpleNamespace(client_id=sensor_id)),
        timeline=None,
        chunk_index=chunk_index,
        windows=(),
    )


def _chunk_result(sensor_id: str, chunk_index: int) -> spectra._SpectralChunkResult:
    return spectra._SpectralChunkResult(
        sensor_id=sensor_id,
        chunk_index=chunk_index,
        freq_hz=(1.0,),
        spectrum_rows=np.zeros((1, 1), dtype=np.float32),
        summaries=(),
    )


def test_execute_chunks_preserves_input_order_while_logging_progress(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chunks = tuple(_chunk("sensor-a", chunk_index) for chunk_index in range(3))

    def fake_process_chunk(*, chunk, metadata):
        time.sleep(0.02 if chunk.chunk_index == 0 else 0.0)
        return _chunk_result(
            sensor_id=chunk.sensor_data.manifest.client_id,
            chunk_index=chunk.chunk_index,
        )

    monkeypatch.setattr(spectra, "_process_chunk", fake_process_chunk)

    with caplog.at_level(logging.INFO, logger=spectra.LOGGER.name):
        results = spectra._execute_chunks(
            chunks=chunks,
            metadata=_metadata(),
            max_workers=2,
        )

    assert [result.chunk_index for result in results] == [0, 1, 2]
    progress_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "whole_run_spectral_chunk_progress"
    ]
    assert progress_records
    assert progress_records[-1].completed_chunks == 3
    assert progress_records[-1].total_chunks == 3


def test_execute_chunks_raises_on_first_completed_failure_without_submitting_full_backlog(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chunks = tuple(_chunk("sensor-a", chunk_index) for chunk_index in range(4))
    started: list[int] = []

    def fake_process_chunk(*, chunk, metadata):
        started.append(chunk.chunk_index)
        if chunk.chunk_index == 0:
            time.sleep(0.05)
            return _chunk_result(sensor_id=chunk.sensor_data.manifest.client_id, chunk_index=0)
        if chunk.chunk_index == 1:
            raise RuntimeError("chunk boom")
        return _chunk_result(
            sensor_id=chunk.sensor_data.manifest.client_id,
            chunk_index=chunk.chunk_index,
        )

    monkeypatch.setattr(spectra, "_process_chunk", fake_process_chunk)

    with caplog.at_level(logging.INFO, logger=spectra.LOGGER.name):
        with pytest.raises(RuntimeError, match="chunk boom"):
            spectra._execute_chunks(
                chunks=chunks,
                metadata=_metadata(),
                max_workers=2,
            )

    assert 2 not in started
    assert 3 not in started
    failure_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "whole_run_spectral_chunk_failed"
    ]
    assert len(failure_records) == 1
    assert failure_records[0].chunk_index == 1
    assert failure_records[0].total_chunks == 4
