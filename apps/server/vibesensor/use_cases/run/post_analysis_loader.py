"""Run loading and bounded sampling for background post-analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil

from vibesensor.shared.ports import RunPersistence
from vibesensor.shared.types.raw_capture import RawCaptureManifest, RawRunCapture
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

_MAX_POST_ANALYSIS_SAMPLES = 12_000
_EVENT_PRESERVING_SAMPLING_METHOD = "event_preserving"


@dataclass(frozen=True, slots=True)
class LoadedPostAnalysisRun:
    run_id: str
    metadata: RunMetadata
    language: str
    samples: list[SensorFrame]
    total_sample_count: int
    stride: int
    sampling_method: str = "full"
    evenly_spaced_sample_count: int = 0
    event_sample_count: int = 0
    context_samples: list[SensorFrame] | None = None
    raw_capture: RawRunCapture | None = None
    raw_capture_manifest: RawCaptureManifest | None = None


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


@dataclass(frozen=True, slots=True)
class _PostAnalysisSampleSelection:
    samples: list[SensorFrame]
    stride: int
    sampling_method: str = "full"
    evenly_spaced_sample_count: int = 0
    event_sample_count: int = 0


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
        raw_capture_manifest: RawCaptureManifest | None = None
        if stored_run is not None:
            metadata = stored_run.metadata
            total_sample_count = max(0, int(stored_run.sample_count))
            raw_capture_manifest = getattr(stored_run, "raw_capture_manifest", None)
        else:
            metadata = await db.aget_run_metadata(run_id)
            if metadata is None:
                return MissingPostAnalysisMetadata(
                    run_id=run_id,
                    error_message="Metadata not found or corrupt; cannot analyse",
                )
            total_sample_count = 0
            get_raw_capture_manifest = getattr(db, "aget_raw_capture_manifest", None)
            if callable(get_raw_capture_manifest):
                raw_capture_manifest = await get_raw_capture_manifest(run_id)

        full_samples: list[SensorFrame] = []
        async for batch in db.aiter_run_samples(run_id, batch_size=1024):
            full_samples.extend(batch)
        samples = full_samples
        if total_sample_count <= 0:
            total_sample_count = len(full_samples)
        if not samples:
            return EmptyPostAnalysisSamples(
                run_id=run_id,
                error_message="No samples collected during run",
            )
        sample_selection = _select_post_analysis_samples(full_samples)
        context_samples: list[SensorFrame] | None = None
        if raw_capture_manifest is not None:
            context_samples = list(full_samples)
        load_raw_capture = getattr(db, "aload_raw_capture", None)
        raw_capture = await load_raw_capture(run_id) if callable(load_raw_capture) else None

        return LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=metadata,
            language=metadata.language or "en",
            samples=sample_selection.samples,
            context_samples=context_samples,
            total_sample_count=total_sample_count,
            stride=sample_selection.stride,
            sampling_method=sample_selection.sampling_method,
            evenly_spaced_sample_count=sample_selection.evenly_spaced_sample_count,
            event_sample_count=sample_selection.event_sample_count,
            raw_capture=raw_capture,
            raw_capture_manifest=raw_capture_manifest,
        )

    runner = getattr(db, "_run_on_engine_loop", None)
    if callable(runner):
        return runner(_aload())  # type: ignore[no-any-return]
    import asyncio as _asyncio

    return _asyncio.run(_aload())


def _select_post_analysis_samples(
    samples: Sequence[SensorFrame],
) -> _PostAnalysisSampleSelection:
    total_sample_count = len(samples)
    stride = _sample_stride(total_sample_count)
    if stride <= 1 or total_sample_count <= _MAX_POST_ANALYSIS_SAMPLES:
        return _PostAnalysisSampleSelection(samples=list(samples), stride=1)
    event_budget = max(1, _MAX_POST_ANALYSIS_SAMPLES // 3)
    evenly_spaced_budget = max(1, _MAX_POST_ANALYSIS_SAMPLES - event_budget)
    evenly_spaced_indices = set(
        _evenly_spaced_indices(total_sample_count, selection_count=evenly_spaced_budget)
    )
    event_indices = _event_preserving_indices(
        samples,
        bucket_count=event_budget,
        exclude=evenly_spaced_indices,
    )
    selected_indices = sorted(evenly_spaced_indices | set(event_indices))
    if len(selected_indices) < _MAX_POST_ANALYSIS_SAMPLES:
        for index in _evenly_spaced_indices(
            total_sample_count,
            selection_count=min(total_sample_count, _MAX_POST_ANALYSIS_SAMPLES * 3),
        ):
            if index in evenly_spaced_indices or index in event_indices:
                continue
            selected_indices.append(index)
            if len(selected_indices) >= _MAX_POST_ANALYSIS_SAMPLES:
                break
        selected_indices.sort()
    return _PostAnalysisSampleSelection(
        samples=[samples[index] for index in selected_indices[:_MAX_POST_ANALYSIS_SAMPLES]],
        stride=stride,
        sampling_method=_EVENT_PRESERVING_SAMPLING_METHOD,
        evenly_spaced_sample_count=len(evenly_spaced_indices),
        event_sample_count=len(set(event_indices) - evenly_spaced_indices),
    )


def _evenly_spaced_indices(total_sample_count: int, *, selection_count: int) -> list[int]:
    if total_sample_count <= 0 or selection_count <= 0:
        return []
    if selection_count >= total_sample_count:
        return list(range(total_sample_count))
    if selection_count == 1:
        return [0]
    last_index = total_sample_count - 1
    return sorted(
        {
            min(last_index, round((last_index * step) / float(selection_count - 1)))
            for step in range(selection_count)
        }
    )


def _event_preserving_indices(
    samples: Sequence[SensorFrame],
    *,
    bucket_count: int,
    exclude: set[int],
) -> list[int]:
    if bucket_count <= 0:
        return []
    total_sample_count = len(samples)
    selected: list[int] = []
    for bucket_index in range(bucket_count):
        start = (bucket_index * total_sample_count) // bucket_count
        end = ((bucket_index + 1) * total_sample_count) // bucket_count
        best_index: int | None = None
        best_score: tuple[float, float, float] | None = None
        for sample_index in range(start, end):
            if sample_index in exclude:
                continue
            score = _sample_event_score(samples[sample_index])
            if best_score is None or score > best_score:
                best_index = sample_index
                best_score = score
        if best_index is not None:
            selected.append(best_index)
    return selected


def _sample_event_score(sample: SensorFrame) -> tuple[float, float, float]:
    strength_db = (
        float(sample.vibration_strength_db)
        if sample.vibration_strength_db is not None
        else float("-inf")
    )
    peak_amp_g = (
        float(sample.strength_peak_amp_g)
        if sample.strength_peak_amp_g is not None
        else float("-inf")
    )
    top_peak_amp_g = max((peak.amp for peak in sample.top_peaks), default=float("-inf"))
    return (strength_db, peak_amp_g, top_peak_amp_g)
