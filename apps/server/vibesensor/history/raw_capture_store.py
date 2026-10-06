"""File-backed raw waveform artifact store for history runs."""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import BinaryIO

import msgspec
import numpy as np

from vibesensor.common.json_contract import JsonContract
from vibesensor.common.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.common.time_utils import utc_now_iso
from vibesensor.recording.raw_capture import (
    RawCaptureChunk,
    RawCaptureChunkIndex,
    RawCaptureChunkTable,
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSampleRateProofState,
    RawCaptureSensorClockSync,
    RawCaptureSensorData,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
    RawRunCapture,
)

LOGGER = logging.getLogger(__name__)

_AXIS_COUNT = 3
_BYTES_PER_AXIS = 2
_BYTES_PER_SAMPLE = _AXIS_COUNT * _BYTES_PER_AXIS
_MANIFEST_FILE_NAME = "manifest.json"
_CHECKPOINT_FILE_NAME = "checkpoint.json"
_DATA_SUFFIX = ".raw.i16le"
_INDEX_SUFFIX = ".index.jsonl"
_RAW_CAPTURE_DIR_NAME = "raw-runs"
_DECLARED_SAMPLE_RATE_ALIGNMENT_TOLERANCE = 0.01


@dataclass(slots=True)
class _OpenSensorStream:
    client_id: str
    sample_rate_hz: int
    data_path: Path
    index_path: Path
    # Unbuffered, so every chunk reaches the OS as it is written and a server
    # crash loses nothing; a power cut loses what was not yet synced.
    data_handle: BinaryIO
    index_handle: BinaryIO
    sample_count: int = 0
    chunk_count: int = 0
    bytes_written: int = 0
    first_t0_us: int | None = None
    last_t0_us: int | None = None


@dataclass(frozen=True, slots=True)
class _CheckpointSensor(JsonContract):
    client_id: str
    sample_rate_hz: int
    clock_sync: RawCaptureSensorClockSync | None = None


@dataclass(frozen=True, slots=True)
class _RecordingCheckpoint(JsonContract):
    """What finalizing needs that the chunk files do not hold, saved while recording.

    A run cut off before Stop (power lost, server killed) has no manifest; the
    startup recovery rebuilds one from the chunk files plus this checkpoint.
    """

    run_start_monotonic_us: int | None = None
    sensors: tuple[_CheckpointSensor, ...] = ()


@dataclass(frozen=True, slots=True)
class _SensorFiles:
    """One sensor's finished data and index files, as the manifest describes them."""

    client_id: str
    declared_sample_rate_hz: int
    data_path: Path
    index_path: Path
    sample_count: int
    chunk_count: int
    bytes_written: int
    first_t0_us: int | None
    last_t0_us: int | None


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
                (
                    safe_json_dumps(
                        RawCaptureChunkIndex(
                            sample_start=stream.sample_count,
                            sample_count=chunk.sample_count,
                            t0_us=chunk.t0_us,
                            byte_offset=byte_offset,
                        ).to_json_object()
                    )
                    + "\n"
                ).encode("utf-8")
            )
            stream.sample_count += chunk.sample_count
            stream.chunk_count += 1
            stream.bytes_written += len(chunk.samples_i16le)
            stream.first_t0_us = chunk.t0_us if stream.first_t0_us is None else stream.first_t0_us
            stream.last_t0_us = chunk.t0_us

    def finalize_run(
        self,
        run_id: str,
        *,
        run_start_monotonic_us: int | None = None,
        sensor_clock_sync: Mapping[str, RawCaptureSensorClockSync] | None = None,
        sensor_losses: Mapping[str, RawCaptureLossStats] | None = None,
    ) -> RawCaptureManifest | None:
        with self._lock:
            streams = self._open_runs.pop(run_id, None)
        if not streams:
            self.delete_run_artifacts(run_id)
            return None
        sensors: list[_SensorFiles] = []
        for client_id in sorted(streams):
            stream = streams[client_id]
            stream.data_handle.close()
            stream.index_handle.close()
            sensors.append(
                _SensorFiles(
                    client_id=stream.client_id,
                    declared_sample_rate_hz=stream.sample_rate_hz,
                    data_path=stream.data_path,
                    index_path=stream.index_path,
                    sample_count=stream.sample_count,
                    chunk_count=stream.chunk_count,
                    bytes_written=stream.bytes_written,
                    first_t0_us=stream.first_t0_us,
                    last_t0_us=stream.last_t0_us,
                )
            )
        return self._write_manifest(
            run_id,
            sensors,
            run_start_monotonic_us=run_start_monotonic_us,
            sensor_clock_sync=sensor_clock_sync,
            sensor_losses=sensor_losses,
        )

    def checkpoint_run(
        self,
        run_id: str,
        *,
        run_start_monotonic_us: int | None,
        sensor_clock_sync: Mapping[str, RawCaptureSensorClockSync] | None,
    ) -> None:
        """Sync the run's chunk files to the disk and save its checkpoint.

        Called every few seconds while recording, so a run cut off by a power
        cut loses at most those seconds and keeps the anchors its replay needs.
        """
        with self._lock:
            streams = self._open_runs.get(run_id)
            if not streams:
                return
            for stream in streams.values():
                os.fsync(stream.data_handle.fileno())
                os.fsync(stream.index_handle.fileno())
            checkpoint = _RecordingCheckpoint(
                run_start_monotonic_us=run_start_monotonic_us,
                sensors=tuple(
                    _CheckpointSensor(
                        client_id=client_id,
                        sample_rate_hz=streams[client_id].sample_rate_hz,
                        clock_sync=(sensor_clock_sync or {}).get(client_id),
                    )
                    for client_id in sorted(streams)
                ),
            )
        run_dir = self.run_dir(run_id)
        temp_path = run_dir / f"{_CHECKPOINT_FILE_NAME}.tmp"
        with temp_path.open("wb") as handle:
            handle.write(safe_json_dumps(checkpoint.to_json_object()).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, run_dir / _CHECKPOINT_FILE_NAME)

    def recover_run(self, run_id: str) -> RawCaptureManifest | None:
        """Rebuild the manifest of a run cut off before Stop from its files on disk.

        Each sensor keeps the longest run of whole chunks its data file holds; a
        chunk the cut left half written is cut off its data and index files. The
        run start and clock proof come from the last checkpoint; a sensor it does
        not cover has no clock proof, so its windows are not replayed. ``None``
        when no chunk survived.
        """
        run_dir = self.run_dir(run_id)
        checkpoint = _load_checkpoint(run_dir / _CHECKPOINT_FILE_NAME)
        checkpoint_sensors = {sensor.client_id: sensor for sensor in checkpoint.sensors}
        sensors: list[_SensorFiles] = []
        index_paths = sorted(run_dir.glob(f"*{_INDEX_SUFFIX}")) if run_dir.is_dir() else []
        for index_path in index_paths:
            client_id = index_path.name.removesuffix(_INDEX_SUFFIX)
            checkpoint_sensor = checkpoint_sensors.get(client_id)
            recovered = _recover_sensor_files(
                client_id,
                data_path=run_dir / f"{client_id}{_DATA_SUFFIX}",
                index_path=index_path,
                declared_sample_rate_hz=(
                    checkpoint_sensor.sample_rate_hz if checkpoint_sensor is not None else 0
                ),
            )
            if recovered is not None:
                sensors.append(recovered)
        if not sensors:
            self.delete_run_artifacts(run_id)
            return None
        return self._write_manifest(
            run_id,
            sensors,
            run_start_monotonic_us=checkpoint.run_start_monotonic_us,
            sensor_clock_sync={
                sensor.client_id: sensor.clock_sync
                for sensor in checkpoint.sensors
                if sensor.clock_sync is not None
            },
            sensor_losses=None,
        )

    def _write_manifest(
        self,
        run_id: str,
        sensors: list[_SensorFiles],
        *,
        run_start_monotonic_us: int | None,
        sensor_clock_sync: Mapping[str, RawCaptureSensorClockSync] | None,
        sensor_losses: Mapping[str, RawCaptureLossStats] | None,
    ) -> RawCaptureManifest:
        sensor_manifests: list[RawCaptureSensorManifest] = []
        sensor_loss_rows: list[RawCaptureSensorLossStats] = []
        total_samples = 0
        total_bytes = 0
        total_losses = RawCaptureLossStats()
        for sensor in sensors:
            (
                sample_rate_hz,
                declared_sample_rate_hz,
                sample_rate_proof_state,
            ) = _derive_sensor_sample_rate(
                sensor.declared_sample_rate_hz, _load_chunk_table(sensor.index_path)
            )
            sensor_manifest = RawCaptureSensorManifest(
                client_id=sensor.client_id,
                sample_rate_hz=sample_rate_hz,
                data_file=sensor.data_path.name,
                index_file=sensor.index_path.name,
                sample_count=sensor.sample_count,
                chunk_count=sensor.chunk_count,
                bytes_written=sensor.bytes_written,
                first_t0_us=sensor.first_t0_us,
                last_t0_us=sensor.last_t0_us,
                clock_sync=(sensor_clock_sync or {}).get(sensor.client_id),
                declared_sample_rate_hz=declared_sample_rate_hz,
                sample_rate_proof_state=sample_rate_proof_state,
            )
            sensor_manifests.append(sensor_manifest)
            total_samples += sensor_manifest.sample_count
            total_bytes += sensor_manifest.bytes_written
        if sensor_losses:
            for client_id in sorted(sensor_losses):
                losses = sensor_losses[client_id]
                if losses.total_loss_event_count <= 0:
                    continue
                sensor_loss_rows.append(
                    RawCaptureSensorLossStats(client_id=client_id, losses=losses)
                )
                total_losses = total_losses.merged(losses)
        manifest = RawCaptureManifest(
            run_id=run_id,
            relative_dir=str(Path(_RAW_CAPTURE_DIR_NAME) / run_id),
            sensors=tuple(sensor_manifests),
            total_samples=total_samples,
            total_bytes=total_bytes,
            created_at=utc_now_iso(),
            run_start_monotonic_us=run_start_monotonic_us,
            sensor_losses=tuple(sensor_loss_rows),
            losses=total_losses,
        )
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / _MANIFEST_FILE_NAME).write_text(
            safe_json_dumps(manifest.to_json_object()),
            encoding="utf-8",
        )
        (run_dir / _CHECKPOINT_FILE_NAME).unlink(missing_ok=True)
        return manifest

    def load_capture(self, manifest: RawCaptureManifest) -> RawRunCapture:
        """Map each sensor's waveform read-only from disk and load its chunk index.

        The waveform is not copied into memory: replay reads only the analysed
        windows, and the kernel can drop those pages again under memory pressure.
        """
        run_dir = self._data_dir / manifest.relative_dir
        sensors: list[RawCaptureSensorData] = []
        for sensor_manifest in manifest.sensors:
            data_path = run_dir / sensor_manifest.data_file
            index_path = run_dir / sensor_manifest.index_file
            sensors.append(
                RawCaptureSensorData(
                    manifest=sensor_manifest,
                    samples_i16=_map_sensor_samples(data_path),
                    chunks=_load_chunk_table(index_path),
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

    def has_run_artifacts(self, run_id: str) -> bool:
        return self.run_dir(run_id).exists()

    def run_dir(self, run_id: str) -> Path:
        return self._base_dir / run_id

    def artifact_files(self, manifest: RawCaptureManifest) -> tuple[Path, ...]:
        """The manifest file plus each sensor's data and index file that exist on disk."""
        run_dir = self.run_dir(manifest.run_id)
        names = [_MANIFEST_FILE_NAME]
        for sensor in manifest.sensors:
            names += [sensor.data_file, sensor.index_file]
        return tuple(path for name in names if (path := run_dir / name).is_file())

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
        data_path = run_dir / f"{client_id}{_DATA_SUFFIX}"
        index_path = run_dir / f"{client_id}{_INDEX_SUFFIX}"
        stream = _OpenSensorStream(
            client_id=client_id,
            sample_rate_hz=sample_rate_hz,
            data_path=data_path,
            index_path=index_path,
            data_handle=data_path.open("ab", buffering=0),
            index_handle=index_path.open("ab", buffering=0),
        )
        run_streams[client_id] = stream
        return stream


def _derive_sensor_sample_rate(
    declared_rate_hz: int,
    chunks: RawCaptureChunkTable,
) -> tuple[int, int | None, RawCaptureSampleRateProofState]:
    declared_sample_rate_hz = declared_rate_hz if declared_rate_hz > 0 else None
    # Chronological like the replay timeline, so a reordered chunk is not a step.
    order = np.lexsort((chunks.sample_start, chunks.t0_us))
    t0_us = chunks.t0_us[order]
    previous_counts = chunks.sample_count[order][:-1]
    delta_t_us = np.diff(t0_us)
    steps = (previous_counts > 0) & (delta_t_us > 0)
    observed_rates_hz: list[float] = (
        (previous_counts[steps] * 1_000_000.0) / delta_t_us[steps]
    ).tolist()
    if not observed_rates_hz:
        if declared_sample_rate_hz is not None:
            return declared_sample_rate_hz, declared_sample_rate_hz, "declared_only"
        return 0, None, "missing"

    representative_rate_hz = _rounded_median(observed_rates_hz)
    if representative_rate_hz <= 0:
        if declared_sample_rate_hz is not None:
            return declared_sample_rate_hz, declared_sample_rate_hz, "declared_only"
        return 0, None, "missing"

    # A dropped chunk or a sensor clock step breaks a chunk-to-chunk step; the
    # median ignores it, and the replay timeline splits there and skips only the
    # windows that cross it.
    if declared_sample_rate_hz is not None:
        declared_delta = abs(representative_rate_hz - declared_sample_rate_hz) / max(
            1,
            declared_sample_rate_hz,
        )
        if declared_delta <= _DECLARED_SAMPLE_RATE_ALIGNMENT_TOLERANCE:
            representative_rate_hz = declared_sample_rate_hz

    return representative_rate_hz, declared_sample_rate_hz, "observed_consistent"


def _load_checkpoint(path: Path) -> _RecordingCheckpoint:
    """The run's last checkpoint; empty when it is missing or unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _RecordingCheckpoint()
    parsed = safe_json_loads(text, context=f"raw capture checkpoint {path}")
    if not isinstance(parsed, dict):
        return _RecordingCheckpoint()
    try:
        return _RecordingCheckpoint.from_mapping(parsed)
    except ValueError:
        LOGGER.warning("Ignoring unreadable raw capture checkpoint %s", path)
        return _RecordingCheckpoint()


def _recover_sensor_files(
    client_id: str,
    *,
    data_path: Path,
    index_path: Path,
    declared_sample_rate_hz: int,
) -> _SensorFiles | None:
    """Keep the leading chunks whose index line and samples both reached the disk.

    Truncates the data file to those chunks and rewrites the index without the
    lines after them, so the files agree with the manifest built from them.
    """
    data_bytes = data_path.stat().st_size if data_path.is_file() else 0
    kept_lines: list[bytes] = []
    sample_count = 0
    first_t0_us: int | None = None
    last_t0_us: int | None = None
    with index_path.open("rb") as handle:
        for line in handle:
            try:
                row = _CHUNK_INDEX_ROW_DECODER.decode(line)
            except msgspec.DecodeError:
                break
            chunk_end_bytes = (row.sample_start + row.sample_count) * _BYTES_PER_SAMPLE
            if (
                row.sample_start != sample_count
                or row.sample_count <= 0
                or chunk_end_bytes > data_bytes
            ):
                break
            kept_lines.append(line if line.endswith(b"\n") else line + b"\n")
            sample_count += row.sample_count
            first_t0_us = row.t0_us if first_t0_us is None else first_t0_us
            last_t0_us = row.t0_us
    if not kept_lines:
        return None
    bytes_written = sample_count * _BYTES_PER_SAMPLE
    if data_bytes != bytes_written:
        with data_path.open("r+b") as handle:
            handle.truncate(bytes_written)
    index_path.write_bytes(b"".join(kept_lines))
    return _SensorFiles(
        client_id=client_id,
        declared_sample_rate_hz=declared_sample_rate_hz,
        data_path=data_path,
        index_path=index_path,
        sample_count=sample_count,
        chunk_count=len(kept_lines),
        bytes_written=bytes_written,
        first_t0_us=first_t0_us,
        last_t0_us=last_t0_us,
    )


class _ChunkIndexRow(msgspec.Struct):
    sample_start: int
    sample_count: int
    t0_us: int


_CHUNK_INDEX_ROW_DECODER = msgspec.json.Decoder(_ChunkIndexRow, strict=False)


def _load_chunk_table(index_path: Path) -> RawCaptureChunkTable:
    """Read a sensor's JSONL chunk index into columns; an unreadable line is skipped."""
    columns: tuple[list[int], list[int], list[int]] = ([], [], [])
    if index_path.exists():
        with index_path.open("rb") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = _CHUNK_INDEX_ROW_DECODER.decode(line)
                except msgspec.DecodeError:
                    LOGGER.warning("Skipping unreadable raw capture index line in %s", index_path)
                    continue
                columns[0].append(row.sample_start)
                columns[1].append(row.sample_count)
                columns[2].append(row.t0_us)
    return RawCaptureChunkTable(
        sample_start=np.array(columns[0], dtype=np.int64),
        sample_count=np.array(columns[1], dtype=np.int64),
        t0_us=np.array(columns[2], dtype=np.int64),
    )


def _map_sensor_samples(data_path: Path) -> np.ndarray:
    """Map a sensor's interleaved little-endian int16 x/y/z file as a read-only ``(n, 3)`` array."""
    size_bytes = data_path.stat().st_size
    if size_bytes % _BYTES_PER_SAMPLE != 0:
        raise ValueError(
            f"raw capture {data_path} length {size_bytes // _BYTES_PER_AXIS} "
            "is not divisible by 3 axes"
        )
    if size_bytes == 0:
        return np.empty((0, _AXIS_COUNT), dtype=np.int16)
    mapped = np.memmap(data_path, dtype=np.dtype("<i2"), mode="r")
    return mapped.reshape(-1, _AXIS_COUNT).view(np.ndarray)


def _rounded_median(values: list[float]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return int(round(ordered[middle]))
    return int(round((ordered[middle - 1] + ordered[middle]) / 2.0))
