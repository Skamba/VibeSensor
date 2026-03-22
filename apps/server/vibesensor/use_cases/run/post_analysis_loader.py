"""Run loading and bounded sampling for background post-analysis."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.sampling import bounded_sample
from vibesensor.shared.types.backend_types import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

_MAX_POST_ANALYSIS_SAMPLES = 12_000


@dataclass(frozen=True, slots=True)
class LoadedPostAnalysisRun:
    run_id: str
    metadata: RunMetadata
    language: str
    samples: list[SensorFrame]
    total_sample_count: int
    stride: int


@dataclass(frozen=True, slots=True)
class MissingPostAnalysisMetadata:
    run_id: str
    error_message: str


@dataclass(frozen=True, slots=True)
class EmptyPostAnalysisSamples:
    run_id: str
    error_message: str


PostAnalysisLoadResult = (
    LoadedPostAnalysisRun | MissingPostAnalysisMetadata | EmptyPostAnalysisSamples
)


def load_post_analysis_run(
    *,
    run_id: str,
    db: RunPersistence,
) -> PostAnalysisLoadResult:
    metadata = db.get_run_metadata(run_id)
    if metadata is None:
        return MissingPostAnalysisMetadata(
            run_id=run_id,
            error_message="Metadata not found or corrupt; cannot analyse",
        )

    sample_iter = (
        sample for batch in db.iter_run_samples(run_id, batch_size=1024) for sample in batch
    )
    samples, total_sample_count, stride = bounded_sample(
        sample_iter,
        max_items=_MAX_POST_ANALYSIS_SAMPLES,
    )
    if not samples:
        return EmptyPostAnalysisSamples(
            run_id=run_id,
            error_message="No samples collected during run",
        )

    return LoadedPostAnalysisRun(
        run_id=run_id,
        metadata=metadata,
        language=metadata.language or "en",
        samples=samples,
        total_sample_count=total_sample_count,
        stride=stride,
    )
