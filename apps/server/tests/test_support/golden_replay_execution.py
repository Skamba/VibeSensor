"""Golden replay executor and benchmark helpers."""

from __future__ import annotations

import tracemalloc
from collections.abc import Mapping
from time import perf_counter
from typing import Any, cast

from test_support.golden_replay_types import (
    GoldenReplayBenchmarkResult,
    GoldenReplayFixture,
    GoldenReplayResult,
)
from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.raw_capture import RawCaptureSensorRange, RawRunCapture
from vibesensor.summary.persisted_analysis import PersistedAnalysis
from vibesensor.summary.whole_run_analysis import WholeRunArtifactManifest
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    raw_capture_range_reader_from_capture,
)
from vibesensor.use_cases.run.post_analysis_executor import (
    PostAnalysisExecutionConfig,
    execute_post_analysis,
)
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput
from vibesensor.use_cases.run.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.use_cases.run.post_analysis_outcomes import PostAnalysisExecutionSuccess
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary


class GoldenReplayRecorder:
    """Minimal persistence port used by the executor harness.

    Raw ranges are served from the fixture's in-memory capture; writes are recorded.
    """

    def __init__(self, raw_capture: RawRunCapture) -> None:
        self._read_range = raw_capture_range_reader_from_capture(raw_capture)
        self.analysis: dict[str, object] | None = None
        self.manifest: WholeRunArtifactManifest | None = None
        self.artifact_contents: dict[str, bytes] = {}
        self.errors: list[tuple[str, str]] = []

    def load_raw_capture_sensor_range(
        self,
        _run_id: str,
        client_id: str,
        *,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange | None:
        return self._read_range(client_id, sample_start=sample_start, sample_count=sample_count)

    def store_whole_run_artifacts(
        self,
        run_id: str,
        manifest: WholeRunArtifactManifest,
        *,
        artifact_contents: Mapping[str, bytes],
    ) -> WholeRunArtifactManifest:
        self.manifest = manifest
        self.artifact_contents = dict(artifact_contents)
        return manifest

    def store_analysis(
        self,
        _run_id: str,
        analysis: PersistedAnalysis | Mapping[str, object],
    ) -> None:
        if isinstance(analysis, PersistedAnalysis):
            self.analysis = cast(dict[str, object], analysis.to_json_object())
        else:
            self.analysis = dict(analysis)

    def store_analysis_error(self, run_id: str, error: str) -> None:
        self.errors.append((run_id, error))


def execute_golden_replay_fixture(
    fixture: GoldenReplayFixture,
    *,
    duration_s: float | None = None,
    analysis_runner: object | None = None,
) -> GoldenReplayResult:
    run = fixture.build(duration_s=duration_s)
    recorder = GoldenReplayRecorder(run.raw_capture)
    result = execute_post_analysis(
        run_id=run.run_id,
        db=cast(RunPersistence, recorder),
        config=PostAnalysisExecutionConfig(
            load_run=lambda *, run_id, db: LoadedPostAnalysisRun(
                run_id=run_id,
                metadata=run.metadata,
                language=run.metadata.language or "en",
                samples=list(run.samples),
                total_summary_row_count=len(run.samples),
                stride=1,
                summary_duration_s=duration_s or fixture.duration_s,
                context_samples=list(run.samples),
                raw_capture=run.raw_capture,
                raw_capture_manifest=run.raw_capture.manifest,
            ),
            analysis_runner=(
                build_post_analysis_summary
                if analysis_runner is None
                else cast(Any, analysis_runner)
            ),
        ),
    )
    assert isinstance(result, PostAnalysisExecutionSuccess)
    assert recorder.analysis is not None
    assert recorder.manifest is not None
    return GoldenReplayResult(
        fixture=fixture,
        analysis=recorder.analysis,
        manifest=recorder.manifest,
        artifact_contents=recorder.artifact_contents,
    )


def benchmark_golden_replay_fixture(
    fixture: GoldenReplayFixture,
    *,
    duration_s: float,
) -> GoldenReplayBenchmarkResult:
    tracemalloc.start()
    started = perf_counter()
    try:
        result = execute_golden_replay_fixture(
            fixture,
            duration_s=duration_s,
            analysis_runner=_minimal_benchmark_summary,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return GoldenReplayBenchmarkResult(
        elapsed_s=perf_counter() - started,
        peak_memory_bytes=peak,
        result=result,
    )


def _minimal_benchmark_summary(run: PostAnalysisRunInput) -> PersistedAnalysis:
    return PersistedAnalysis.from_json_object(
        {
            "run_id": run.run_id,
            "findings": [],
            "top_causes": [],
            "warnings": [],
            "run_suitability": [],
            "analysis_metadata": {
                "analyzed_sample_count": len(run.samples),
                "benchmark_fixture": run.run_id,
            },
        }
    )
