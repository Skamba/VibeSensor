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
    RawCaptureManifest,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)

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
            raw_bytes = data_path.read_bytes()
            samples_i16 = np.frombuffer(raw_bytes, dtype=np.dtype("<i2")).copy()
            if samples_i16.size % 3 != 0:
                raise ValueError(
                    f"raw capture {data_path} length {samples_i16.size} is not divisible by 3 axes"
                )
            reshaped = samples_i16.reshape(-1, 3)
            index_path = run_dir / sensor_manifest.index_file
            chunk_indexes: list[RawCaptureChunkIndex] = []
            if index_path.exists():
                for line in index_path.read_text(encoding="utf-8").splitlines():
                    parsed = safe_json_loads(line, context=f"raw capture index {index_path}")
                    if is_json_object(parsed):
                        chunk_indexes.append(RawCaptureChunkIndex.from_mapping(parsed))
            sensors.append(
                RawCaptureSensorData(
                    manifest=sensor_manifest,
                    samples_i16=reshaped,
                    chunks=tuple(chunk_indexes),
                )
            )
        return RawRunCapture(manifest=manifest, sensors=tuple(sensors))

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
