"""File-backed raw waveform artifact store for history runs."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import BinaryIO, TextIO

import numpy as np

from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.raw_capture import (
    RawCaptureChunk,
    RawCaptureChunkIndex,
    RawCaptureCoverageState,
    RawCaptureManifest,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawCaptureSensorRange,
    RawRunCapture,
)

_AXIS_COUNT = 3
_BYTES_PER_AXIS = 2
_BYTES_PER_SAMPLE = _AXIS_COUNT * _BYTES_PER_AXIS
_MANIFEST_FILE_NAME = "manifest.json"
_RAW_CAPTURE_DIR_NAME = "raw-runs"


@dataclass(slots=True)
class _OpenSensorStream:
    client_id: str
    sample_rate_hz: int
    data_path: Path
    index_path: Path
    data_handle: BinaryIO
    index_handle: TextIO
    sample_count: int = 0
    chunk_count: int = 0
    bytes_written: int = 0
    first_t0_us: int | None = None
    last_t0_us: int | None = None


class HistoryRawCaptureStore:
    """Store raw waveform artifacts in deterministic per-run directories."""

    __slots__ = ("_base_dir", "_data_dir", "_lock", "_open_runs")

    def __init__(self, *, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._base_dir = data_dir / _RAW_CAPTURE_DIR_NAME
        self._lock = RLock()
        self._open_runs: dict[str, dict[str, _OpenSensorStream]] = {}

    def append_chunk(self, run_id: str, chunk: RawCaptureChunk) -> None:
        with self._lock:
            stream = self._ensure_stream(run_id, chunk.client_id, chunk.sample_rate_hz)
            if stream.sample_rate_hz != chunk.sample_rate_hz:
                raise ValueError(
                    f"raw capture sample-rate mismatch for {chunk.client_id}: "
                    f"{stream.sample_rate_hz} != {chunk.sample_rate_hz}"
                )
            byte_offset = stream.bytes_written
            stream.data_handle.write(chunk.samples_i16le)
            stream.index_handle.write(
                safe_json_dumps(
                    RawCaptureChunkIndex(
                        sample_start=stream.sample_count,
                        sample_count=chunk.sample_count,
                        t0_us=chunk.t0_us,
                        byte_offset=byte_offset,
                    ).to_json_object()
                )
                + "\n"
            )
            stream.sample_count += chunk.sample_count
            stream.chunk_count += 1
            stream.bytes_written += len(chunk.samples_i16le)
            stream.first_t0_us = chunk.t0_us if stream.first_t0_us is None else stream.first_t0_us
            stream.last_t0_us = chunk.t0_us

    def finalize_run(self, run_id: str) -> RawCaptureManifest | None:
        with self._lock:
            streams = self._open_runs.pop(run_id, None)
        if not streams:
            self.delete_run_artifacts(run_id)
            return None
        sensor_manifests: list[RawCaptureSensorManifest] = []
        total_samples = 0
        total_bytes = 0
        for client_id in sorted(streams):
            stream = streams[client_id]
            stream.data_handle.close()
            stream.index_handle.close()
            sensor_manifest = RawCaptureSensorManifest(
                client_id=stream.client_id,
                sample_rate_hz=stream.sample_rate_hz,
                data_file=stream.data_path.name,
                index_file=stream.index_path.name,
                sample_count=stream.sample_count,
                chunk_count=stream.chunk_count,
                bytes_written=stream.bytes_written,
                first_t0_us=stream.first_t0_us,
                last_t0_us=stream.last_t0_us,
            )
            sensor_manifests.append(sensor_manifest)
            total_samples += sensor_manifest.sample_count
            total_bytes += sensor_manifest.bytes_written
        manifest = RawCaptureManifest(
            run_id=run_id,
            relative_dir=str(Path(_RAW_CAPTURE_DIR_NAME) / run_id),
            sensors=tuple(sensor_manifests),
            total_samples=total_samples,
            total_bytes=total_bytes,
            created_at=utc_now_iso(),
        )
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / _MANIFEST_FILE_NAME).write_text(
            safe_json_dumps(manifest.to_json_object()),
            encoding="utf-8",
        )
        return manifest

    def load_capture(self, manifest: RawCaptureManifest) -> RawRunCapture:
        run_dir = self._data_dir / manifest.relative_dir
        sensors: list[RawCaptureSensorData] = []
        for sensor_manifest in manifest.sensors:
            data_path = run_dir / sensor_manifest.data_file
            index_path = run_dir / sensor_manifest.index_file
            reshaped = self._read_all_sensor_samples(data_path)
            chunk_indexes = self._load_chunk_indexes(index_path)
            sensors.append(
                RawCaptureSensorData(
                    manifest=sensor_manifest,
                    samples_i16=reshaped,
                    chunks=tuple(chunk_indexes),
                )
            )
        return RawRunCapture(manifest=manifest, sensors=tuple(sensors))

    def load_sensor_range(
        self,
        manifest: RawCaptureManifest,
        *,
        client_id: str,
        sample_start: int,
        sample_count: int,
    ) -> RawCaptureSensorRange:
        if sample_start < 0:
            raise ValueError("raw capture range requires sample_start >= 0")
        if sample_count <= 0:
            raise ValueError("raw capture range requires sample_count > 0")
        sensor_manifest = manifest.sensor_manifest(client_id)
        if sensor_manifest is None:
            return RawCaptureSensorRange.missing(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
            )
        available_count = max(0, int(sensor_manifest.sample_count))
        if sample_start >= available_count:
            return RawCaptureSensorRange(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
                coverage_state="empty",
                samples_i16=np.empty((0, _AXIS_COUNT), dtype=np.int16),
                manifest=sensor_manifest,
                returned_sample_start=sample_start,
            )
        actual_start = sample_start
        actual_end = min(sample_start + sample_count, available_count)
        actual_count = max(0, actual_end - actual_start)
        if actual_count <= 0:
            return RawCaptureSensorRange(
                client_id=client_id,
                requested_sample_start=sample_start,
                requested_sample_count=sample_count,
                coverage_state="empty",
                samples_i16=np.empty((0, _AXIS_COUNT), dtype=np.int16),
                manifest=sensor_manifest,
                returned_sample_start=sample_start,
            )
        run_dir = self._data_dir / manifest.relative_dir
        index_path = run_dir / sensor_manifest.index_file
        chunk_indexes = tuple(self._load_chunk_indexes(index_path))
        overlapping_chunks = _overlapping_chunks(
            chunk_indexes,
            sample_start=actual_start,
            sample_end=actual_end,
        )
        if not overlapping_chunks:
            raise ValueError(
                f"raw capture index {index_path} has no chunk coverage for "
                f"{client_id} samples [{actual_start}, {actual_end})"
            )
        first_chunk = overlapping_chunks[0]
        byte_offset = first_chunk.byte_offset + (
            (actual_start - first_chunk.sample_start) * _BYTES_PER_SAMPLE
        )
        samples_i16 = self._read_sensor_range_samples(
            run_dir / sensor_manifest.data_file,
            byte_offset=byte_offset,
            sample_count=actual_count,
        )
        returned_count = int(samples_i16.shape[0])
        coverage_state: RawCaptureCoverageState = (
            "full" if returned_count == sample_count else "partial"
        )
        if returned_count <= 0:
            coverage_state = "empty"
        return RawCaptureSensorRange(
            client_id=client_id,
            requested_sample_start=sample_start,
            requested_sample_count=sample_count,
            coverage_state=coverage_state,
            samples_i16=samples_i16,
            manifest=sensor_manifest,
            returned_sample_start=actual_start,
            chunks=overlapping_chunks,
        )

    def delete_run_artifacts(self, run_id: str) -> None:
        with self._lock:
            streams = self._open_runs.pop(run_id, None)
        if streams:
            for stream in streams.values():
                stream.data_handle.close()
                stream.index_handle.close()
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def run_dir(self, run_id: str) -> Path:
        return self._base_dir / run_id

    def _load_chunk_indexes(self, index_path: Path) -> list[RawCaptureChunkIndex]:
        chunk_indexes: list[RawCaptureChunkIndex] = []
        if not index_path.exists():
            return chunk_indexes
        for line in index_path.read_text(encoding="utf-8").splitlines():
            parsed = safe_json_loads(line, context=f"raw capture index {index_path}")
            if is_json_object(parsed):
                chunk_indexes.append(RawCaptureChunkIndex.from_mapping(parsed))
        return chunk_indexes

    def _read_all_sensor_samples(self, data_path: Path) -> np.ndarray:
        return self._reshape_samples(raw_bytes=data_path.read_bytes(), data_path=data_path)

    def _read_sensor_range_samples(
        self,
        data_path: Path,
        *,
        byte_offset: int,
        sample_count: int,
    ) -> np.ndarray:
        with data_path.open("rb") as handle:
            handle.seek(byte_offset)
            raw_bytes = handle.read(sample_count * _BYTES_PER_SAMPLE)
        return self._reshape_samples(raw_bytes=raw_bytes, data_path=data_path)

    def _reshape_samples(self, *, raw_bytes: bytes, data_path: Path) -> np.ndarray:
        samples_i16 = np.frombuffer(raw_bytes, dtype=np.dtype("<i2")).copy()
        if samples_i16.size % _AXIS_COUNT != 0:
            raise ValueError(
                f"raw capture {data_path} length {samples_i16.size} is not divisible by 3 axes"
            )
        return samples_i16.reshape(-1, _AXIS_COUNT)

    def _ensure_stream(
        self,
        run_id: str,
        client_id: str,
        sample_rate_hz: int,
    ) -> _OpenSensorStream:
        run_streams = self._open_runs.setdefault(run_id, {})
        existing = run_streams.get(client_id)
        if existing is not None:
            return existing
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        data_path = run_dir / f"{client_id}.raw.i16le"
        index_path = run_dir / f"{client_id}.index.jsonl"
        stream = _OpenSensorStream(
            client_id=client_id,
            sample_rate_hz=sample_rate_hz,
            data_path=data_path,
            index_path=index_path,
            data_handle=data_path.open("ab"),
            index_handle=index_path.open("a", encoding="utf-8"),
        )
        run_streams[client_id] = stream
        return stream


def _overlapping_chunks(
    chunks: tuple[RawCaptureChunkIndex, ...],
    *,
    sample_start: int,
    sample_end: int,
) -> tuple[RawCaptureChunkIndex, ...]:
    return tuple(
        chunk
        for chunk in chunks
        if chunk.sample_start < sample_end
        and (chunk.sample_start + chunk.sample_count) > sample_start
    )
