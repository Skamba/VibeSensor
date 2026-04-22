"""Run loading and bounded sampling for background post-analysis."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.raw_capture import RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
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
    raw_capture: RawRunCapture | None = None


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


def _sample_stride(total_sample_count: int) -> int:
    """Return the minimum stride that keeps bounded post-analysis under the sample cap."""
    if total_sample_count <= _MAX_POST_ANALYSIS_SAMPLES:
        return 1
    return ceil(total_sample_count / _MAX_POST_ANALYSIS_SAMPLES)


def load_post_analysis_run(
    *,
    run_id: str,
    db: RunPersistence,
) -> PostAnalysisLoadResult:
    async def _aload() -> PostAnalysisLoadResult:
        aget_run = getattr(db, "aget_run", None)
        stored_run = await aget_run(run_id) if callable(aget_run) else None
        if stored_run is not None:
            metadata = stored_run.metadata
            total_sample_count = max(0, int(stored_run.sample_count))
        else:
            metadata = await db.aget_run_metadata(run_id)
            if metadata is None:
                return MissingPostAnalysisMetadata(
                    run_id=run_id,
                    error_message="Metadata not found or corrupt; cannot analyse",
                )
            total_sample_count = 0

        stride = _sample_stride(total_sample_count)
        samples: list[SensorFrame] = []
        if stored_run is not None:
            async for batch in db.aiter_run_samples(run_id, batch_size=1024, stride=stride):
                samples.extend(batch)
        else:
            async for batch in db.aiter_run_samples(run_id, batch_size=1024):
                samples.extend(batch)
        if total_sample_count <= 0:
            total_sample_count = len(samples)
        if not samples:
            return EmptyPostAnalysisSamples(
                run_id=run_id,
                error_message="No samples collected during run",
            )
        load_raw_capture = getattr(db, "aload_raw_capture", None)
        raw_capture = await load_raw_capture(run_id) if callable(load_raw_capture) else None

        return LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=metadata,
            language=metadata.language or "en",
            samples=samples,
            total_sample_count=total_sample_count,
            stride=stride,
            raw_capture=raw_capture,
        )

    runner = getattr(db, "_run_on_engine_loop", None)
    if callable(runner):
        return runner(_aload())  # type: ignore[no-any-return]
    import asyncio as _asyncio

    return _asyncio.run(_aload())
