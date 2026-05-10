from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_support.persisted_analysis import make_persisted_analysis
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run.post_analysis_executor import (
    PostAnalysisExecutionConfig,
    execute_post_analysis,
)
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput
from vibesensor.use_cases.run.post_analysis_loader import (
    EmptyPostAnalysisSamples,
    LoadedPostAnalysisRun,
    MissingPostAnalysisMetadata,
)
from vibesensor.use_cases.run.post_analysis_outcomes import (
    PostAnalysisExecutionMissingMetadata,
    PostAnalysisExecutionNoSamples,
    PostAnalysisExecutionPersistenceFailure,
    PostAnalysisExecutionRetryableFailure,
    PostAnalysisExecutionSuccess,
)


def _run_metadata(run_id: str, *, language: str = "en") -> RunMetadata:
    return run_metadata_from_mapping(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": 800,
            "sample_rate_hz": 800,
            "feature_interval_s": 1.0,
            "language": language,
        }
    )


def _samples() -> list:
    return sensor_frames_from_mappings([{"t_s": 1.0, "vibration_strength_db": 10.0}])


def _config(
    *,
    analysis_runner,
    load_run,
    defer_retryable_error_storage=False,
):
    return PostAnalysisExecutionConfig(
        analysis_runner=analysis_runner,
        load_run=load_run,
        defer_retryable_error_storage=defer_retryable_error_storage,
    )


def test_execute_post_analysis_success_stores_summary() -> None:
    stored: dict[str, object] = {}

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            stored["run_id"] = run_id
            stored["analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    result = execute_post_analysis(
        run_id="run-ok",
        db=FakeDB(),
        config=_config(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id, language="nl"),
                language="nl",
                samples=_samples(),
                total_summary_row_count=1,
                stride=1,
            ),
            analysis_runner=lambda run: make_persisted_analysis(
                {
                    "lang": run.language,
                    "row_count": len(run.samples),
                    "analysis_metadata": {
                        "analyzed_sample_count": len(run.samples),
                        "total_sample_count": run.total_summary_row_count,
                        "sampling_method": "full",
                    },
                    "run_suitability": [],
                }
            ),
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert stored["run_id"] == "run-ok"
    assert stored["analysis"]["lang"] == "nl"


def test_execute_post_analysis_exports_trace_span(tmp_path: Path) -> None:
    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            return None

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    with configured_trace_output(tmp_path) as trace_path:
        result = execute_post_analysis(
            run_id="run-trace",
            db=FakeDB(),
            config=_config(
                load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                    run_id=run_id,
                    metadata=_run_metadata(run_id),
                    language="en",
                    samples=_samples(),
                    total_summary_row_count=1,
                    stride=1,
                ),
                analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
            ),
        )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    span = next(
        item
        for item in read_trace_output(trace_path)
        if item["name"] == "run.post_analysis.execute"
    )
    assert span["attributes"]["vibesensor.run_id"] == "run-trace"
    assert span["attributes"]["vibesensor.sample_count"] == 1


def test_execute_post_analysis_handles_missing_metadata() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-missing",
        db=FakeDB(),
        config=_config(
            load_run=lambda *, run_id, db: MissingPostAnalysisMetadata(
                run_id=run_id,
                error_message="Metadata not found or corrupt; cannot analyse",
            ),
            analysis_runner=lambda _run: make_persisted_analysis({}),
        ),
    )

    assert isinstance(result, PostAnalysisExecutionMissingMetadata)
    assert result.completed_error == "Metadata not found or corrupt; cannot analyse"
    assert stored_errors == [("run-missing", "Metadata not found or corrupt; cannot analyse")]


def test_execute_post_analysis_handles_no_samples() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-empty",
        db=FakeDB(),
        config=_config(
            load_run=lambda *, run_id, db: EmptyPostAnalysisSamples(
                run_id=run_id,
                error_message="No samples collected during run",
            ),
            analysis_runner=lambda _run: make_persisted_analysis({}),
        ),
    )

    assert isinstance(result, PostAnalysisExecutionNoSamples)
    assert result.completed_error == "No samples collected during run"
    assert stored_errors == [("run-empty", "No samples collected during run")]


def test_execute_post_analysis_propagates_unexpected_analysis_failure() -> None:
    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    with pytest.raises(RuntimeError, match="boom"):
        execute_post_analysis(
            run_id="run-fail",
            db=FakeDB(),
            config=_config(
                load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                    run_id=run_id,
                    metadata=_run_metadata(run_id),
                    language="en",
                    samples=_samples(),
                    total_summary_row_count=1,
                    stride=1,
                ),
                analysis_runner=lambda _run: (_ for _ in ()).throw(RuntimeError("boom")),
            ),
        )


def test_execute_post_analysis_reports_persistence_failure() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise sqlite3.Error("db write failed")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-store-fail",
        db=FakeDB(),
        config=_config(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id),
                language="en",
                samples=_samples(),
                total_summary_row_count=1,
                stride=1,
            ),
            analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
        ),
    )

    assert isinstance(result, PostAnalysisExecutionPersistenceFailure)
    assert result.completed_error == "db write failed"
    assert result.callback_errors == (
        "post-analysis failed for run run-store-fail: db write failed",
    )
    assert stored_errors == [("run-store-fail", "db write failed")]


def test_execute_post_analysis_defers_retryable_persistence_failure() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise sqlite3.OperationalError("db locked")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-retry",
        db=FakeDB(),
        config=_config(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id),
                language="en",
                samples=_samples(),
                total_summary_row_count=1,
                stride=1,
            ),
            analysis_runner=lambda _run: make_persisted_analysis({"run_suitability": []}),
            defer_retryable_error_storage=True,
        ),
    )

    assert isinstance(result, PostAnalysisExecutionRetryableFailure)
    assert result.error_message == "db locked"
    assert result.callback_errors == ("post-analysis failed for run run-retry: db locked",)
    assert stored_errors == []


def test_execute_post_analysis_defers_retryable_load_failure() -> None:
    stored_errors: list[tuple[str, str]] = []

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            raise AssertionError(f"unexpected store_analysis({run_id}, {analysis})")

        async def astore_analysis_error(self, run_id, error):
            stored_errors.append((run_id, error))

    result = execute_post_analysis(
        run_id="run-load-retry",
        db=FakeDB(),
        config=_config(
            load_run=lambda *, run_id, db: (_ for _ in ()).throw(
                sqlite3.OperationalError("db busy")
            ),
            analysis_runner=lambda _run: make_persisted_analysis({}),
            defer_retryable_error_storage=True,
        ),
    )

    assert isinstance(result, PostAnalysisExecutionRetryableFailure)
    assert result.error_message == "db busy"
    assert stored_errors == []


def test_execute_post_analysis_passes_canonical_typed_input_to_runner() -> None:
    captured: dict[str, object] = {}

    class FakeDB:
        async def astore_analysis(self, run_id, analysis):
            captured["stored_run_id"] = run_id
            captured["stored_analysis"] = analysis

        async def astore_analysis_error(self, run_id, error):
            raise AssertionError(f"unexpected store_analysis_error({run_id}, {error})")

    result = execute_post_analysis(
        run_id="run-input",
        db=FakeDB(),
        config=_config(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=_run_metadata(run_id, language="nl"),
                language="nl",
                samples=_samples(),
                total_summary_row_count=1,
                stride=1,
            ),
            analysis_runner=lambda run: _capture_run_input(captured, run),
        ),
    )

    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert captured["run_input_type"] is PostAnalysisRunInput
    assert captured["context_run_id"] == "run-input"
    assert captured["sample_type"] == "SensorFrame"


def _capture_run_input(captured: dict[str, object], run: PostAnalysisRunInput):
    captured["run_input_type"] = type(run)
    captured["context_run_id"] = run.context.run_id
    captured["sample_type"] = type(run.samples[0]).__name__
    return make_persisted_analysis({"run_suitability": []})
