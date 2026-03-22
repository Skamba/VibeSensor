from __future__ import annotations

import pytest

from vibesensor.shared.types.backend_types import RunMetadata
from vibesensor.use_cases.run.post_analysis_loader import (
    EmptyPostAnalysisSamples,
    LoadedPostAnalysisRun,
    MissingPostAnalysisMetadata,
    load_post_analysis_run,
)


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
    return RunMetadata.from_dict(payload)


def test_load_post_analysis_run_returns_loaded_run() -> None:
    class FakeDB:
        def get_run_metadata(self, run_id):
            return _run_metadata(run_id, language="nl")

        def iter_run_samples(self, run_id, batch_size=1024):
            assert run_id == "run-ok"
            assert batch_size == 1024
            yield [
                {"t_s": 1.0, "vibration_strength_db": 10.0},
                {"t_s": 2.0, "vibration_strength_db": 11.0},
            ]

    result = load_post_analysis_run(run_id="run-ok", db=FakeDB())

    assert isinstance(result, LoadedPostAnalysisRun)
    assert result.run_id == "run-ok"
    assert result.language == "nl"
    assert result.total_sample_count == 2
    assert result.stride == 1
    assert len(result.samples) == 2


def test_load_post_analysis_run_handles_missing_metadata() -> None:
    class FakeDB:
        def get_run_metadata(self, _run_id):
            return None

    result = load_post_analysis_run(run_id="run-missing", db=FakeDB())

    assert isinstance(result, MissingPostAnalysisMetadata)
    assert result.run_id == "run-missing"
    assert "Metadata" in result.error_message


def test_load_post_analysis_run_handles_no_samples() -> None:
    class FakeDB:
        def get_run_metadata(self, run_id):
            return _run_metadata(run_id)

        def iter_run_samples(self, _run_id, batch_size=1024):
            return iter([])

    result = load_post_analysis_run(run_id="run-empty", db=FakeDB())

    assert isinstance(result, EmptyPostAnalysisSamples)
    assert result.run_id == "run-empty"
    assert "samples" in result.error_message.lower()


def test_load_post_analysis_run_applies_bounded_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_loader._MAX_POST_ANALYSIS_SAMPLES",
        2,
    )

    class FakeDB:
        def get_run_metadata(self, run_id):
            return _run_metadata(run_id)

        def iter_run_samples(self, _run_id, batch_size=1024):
            yield [
                {"t_s": 1.0, "vibration_strength_db": 10.0},
                {"t_s": 2.0, "vibration_strength_db": 11.0},
                {"t_s": 3.0, "vibration_strength_db": 12.0},
                {"t_s": 4.0, "vibration_strength_db": 13.0},
            ]

    result = load_post_analysis_run(run_id="run-capped", db=FakeDB())

    assert isinstance(result, LoadedPostAnalysisRun)
    assert len(result.samples) == 2
    assert result.total_sample_count == 4
    assert result.stride == 2


def test_load_post_analysis_run_defaults_language_to_en() -> None:
    class FakeDB:
        def get_run_metadata(self, run_id):
            return _run_metadata(run_id, language=None)

        def iter_run_samples(self, _run_id, batch_size=1024):
            yield [{"t_s": 1.0, "vibration_strength_db": 10.0}]

    result = load_post_analysis_run(run_id="run-lang", db=FakeDB())

    assert isinstance(result, LoadedPostAnalysisRun)
    assert result.language == "en"
