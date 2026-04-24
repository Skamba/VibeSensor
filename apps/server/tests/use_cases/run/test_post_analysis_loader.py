from __future__ import annotations

from dataclasses import dataclass

import pytest

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawCaptureSensorRange
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run.post_analysis_loader import (
    EmptyPostAnalysisSamples,
    LoadedPostAnalysisRun,
    MissingPostAnalysisMetadata,
    load_post_analysis_run,
)


@dataclass(slots=True)
class _StoredRun:
    metadata: RunMetadata
    sample_count: int
    raw_capture_manifest: RawCaptureManifest | None = None


def _run_metadata(run_id: str, *, language: str | None = "en") -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2025-01-01T00:00:00Z",
        "sensor_model": "fixture-sensor",
        "raw_sample_rate_hz": 800,
        "sample_rate_hz": 800,
        "feature_interval_s": 1.0,
    }
    if language is not None:
        payload["language"] = language
    return run_metadata_from_mapping(payload)


def test_load_post_analysis_run_returns_loaded_run() -> None:
    class FakeDB:
        async def aget_run(self, run_id):
            return _StoredRun(
                metadata=_run_metadata(run_id, language="nl"),
                sample_count=2,
            )

        async def aiter_run_samples(self, run_id, batch_size=1024, *, stride=1):
            assert run_id == "run-ok"
            assert batch_size == 1024
            assert stride == 1
            yield sensor_frames_from_mappings(
                [
                    {"t_s": 1.0, "vibration_strength_db": 10.0},
                    {"t_s": 2.0, "vibration_strength_db": 11.0},
                ]
            )

        async def aload_raw_capture(self, _run_id):
            return None

        async def aload_raw_capture_sensor_range(
            self,
            _run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    result = load_post_analysis_run(run_id="run-ok", db=FakeDB())

    assert isinstance(result, LoadedPostAnalysisRun)
    assert result.run_id == "run-ok"
    assert result.language == "nl"
    assert result.total_summary_row_count == 2
    assert result.summary_duration_s == pytest.approx(1.0)
    assert result.stride == 1
    assert len(result.samples) == 2


def test_load_post_analysis_run_handles_missing_metadata() -> None:
    class FakeDB:
        async def aget_run(self, _run_id):
            return None

        async def aget_run_metadata(self, _run_id):
            return None

        async def aload_raw_capture(self, _run_id):
            return None

        async def aload_raw_capture_sensor_range(
            self,
            _run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    result = load_post_analysis_run(run_id="run-missing", db=FakeDB())

    assert isinstance(result, MissingPostAnalysisMetadata)
    assert result.run_id == "run-missing"
    assert "Metadata" in result.error_message


def test_load_post_analysis_run_handles_no_samples() -> None:
    class FakeDB:
        async def aget_run(self, run_id):
            return _StoredRun(metadata=_run_metadata(run_id), sample_count=0)

        async def aiter_run_samples(self, _run_id, batch_size=1024, *, stride=1):
            assert stride == 1
            return
            yield  # pragma: no cover

        async def aload_raw_capture(self, _run_id):
            return None

        async def aload_raw_capture_sensor_range(
            self,
            _run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    result = load_post_analysis_run(run_id="run-empty", db=FakeDB())

    assert isinstance(result, EmptyPostAnalysisSamples)
    assert result.run_id == "run-empty"
    assert "samples" in result.error_message.lower()


def test_load_post_analysis_run_preserves_transient_events_when_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_loader._MAX_POST_ANALYSIS_SAMPLES",
        2,
    )
    iter_calls: list[tuple[int, int]] = []

    class FakeDB:
        async def aget_run(self, run_id):
            return _StoredRun(metadata=_run_metadata(run_id), sample_count=4)

        async def aiter_run_samples(self, _run_id, batch_size=1024, *, stride=1):
            iter_calls.append((batch_size, stride))
            yield sensor_frames_from_mappings(
                [
                    {"t_s": 1.0, "vibration_strength_db": 10.0},
                    {"t_s": 2.0, "vibration_strength_db": 11.0},
                    {"t_s": 3.0, "vibration_strength_db": 48.0},
                    {"t_s": 4.0, "vibration_strength_db": 12.0},
                ]
            )

        async def aload_raw_capture(self, _run_id):
            return None

        async def aload_raw_capture_sensor_range(
            self,
            _run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    result = load_post_analysis_run(run_id="run-capped", db=FakeDB())

    assert isinstance(result, LoadedPostAnalysisRun)
    assert len(result.samples) == 2
    assert result.total_summary_row_count == 4
    assert result.summary_duration_s == pytest.approx(3.0)
    assert result.stride == 2
    assert result.sampling_method == "event_preserving"
    assert result.event_sample_count == 1
    assert [sample.t_s for sample in result.samples] == [1.0, 3.0]
    assert iter_calls == [(1024, 1)]


def test_load_post_analysis_run_keeps_event_preserving_selection_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_loader._MAX_POST_ANALYSIS_SAMPLES",
        3,
    )

    class FakeDB:
        async def aget_run(self, run_id):
            return _StoredRun(metadata=_run_metadata(run_id), sample_count=6)

        async def aiter_run_samples(self, _run_id, batch_size=1024, *, stride=1):
            assert batch_size == 1024
            assert stride == 1
            yield sensor_frames_from_mappings(
                [
                    {"t_s": 1.0, "vibration_strength_db": 10.0},
                    {"t_s": 2.0, "vibration_strength_db": 11.0},
                    {"t_s": 3.0, "vibration_strength_db": 12.0},
                    {"t_s": 4.0, "vibration_strength_db": 13.0},
                    {"t_s": 5.0, "vibration_strength_db": 14.0},
                    {"t_s": 6.0, "vibration_strength_db": 15.0},
                ]
            )

        async def aload_raw_capture(self, _run_id):
            return None

        async def aload_raw_capture_sensor_range(
            self,
            _run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    first = load_post_analysis_run(run_id="run-deterministic", db=FakeDB())
    second = load_post_analysis_run(run_id="run-deterministic", db=FakeDB())

    assert isinstance(first, LoadedPostAnalysisRun)
    assert isinstance(second, LoadedPostAnalysisRun)
    assert len(first.samples) == 3
    assert len(second.samples) == 3
    assert first.sampling_method == "event_preserving"
    assert [sample.t_s for sample in first.samples] == [sample.t_s for sample in second.samples]


def test_load_post_analysis_run_loads_full_context_samples_when_whole_run_artifacts_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_loader._MAX_POST_ANALYSIS_SAMPLES",
        2,
    )
    raw_capture_manifest = RawCaptureManifest(
        run_id="run-context",
        relative_dir="raw-runs/run-context",
        sensors=(),
        total_samples=4,
        total_bytes=0,
        created_at="2025-01-01T00:00:00Z",
    )

    class FakeDB:
        async def aget_run(self, run_id):
            return _StoredRun(
                metadata=_run_metadata(run_id),
                sample_count=4,
                raw_capture_manifest=raw_capture_manifest,
            )

        async def aiter_run_samples(self, _run_id, batch_size=1024, *, stride=1):
            assert batch_size == 1024
            assert stride == 1
            yield sensor_frames_from_mappings(
                [
                    {"t_s": 1.0, "vibration_strength_db": 10.0},
                    {"t_s": 2.0, "vibration_strength_db": 11.0},
                    {"t_s": 3.0, "vibration_strength_db": 12.0},
                    {"t_s": 4.0, "vibration_strength_db": 13.0},
                ]
            )

        async def aget_run_samples(self, _run_id):
            return sensor_frames_from_mappings(
                [
                    {"t_s": 1.0, "vibration_strength_db": 10.0},
                    {"t_s": 2.0, "vibration_strength_db": 11.0},
                    {"t_s": 3.0, "vibration_strength_db": 12.0},
                    {"t_s": 4.0, "vibration_strength_db": 13.0},
                ]
            )

        async def aload_raw_capture(self, _run_id):
            return None

        async def aload_raw_capture_sensor_range(
            self,
            _run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    result = load_post_analysis_run(run_id="run-context", db=FakeDB())

    assert isinstance(result, LoadedPostAnalysisRun)
    assert len(result.samples) == 2
    assert result.context_samples is not None
    assert len(result.context_samples) == 4
    assert result.stride == 2
    assert result.sampling_method == "event_preserving"


def test_load_post_analysis_run_defaults_language_to_en() -> None:
    class FakeDB:
        async def aget_run(self, run_id):
            return _StoredRun(
                metadata=_run_metadata(run_id, language=None),
                sample_count=1,
            )

        async def aiter_run_samples(self, _run_id, batch_size=1024, *, stride=1):
            assert stride == 1
            yield sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}])

        async def aload_raw_capture(self, _run_id):
            return None

        async def aload_raw_capture_sensor_range(
            self,
            _run_id,
            client_id,
            *,
            sample_start,
            sample_count,
        ):
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )

    result = load_post_analysis_run(run_id="run-lang", db=FakeDB())

    assert isinstance(result, LoadedPostAnalysisRun)
    assert result.language == "en"
    assert result.raw_capture is None
