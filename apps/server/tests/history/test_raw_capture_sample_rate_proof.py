"""Sample-rate proof of a finalized raw capture: isolated timing breaks do not void it."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vibesensor.history.raw_capture_store import HistoryRawCaptureStore
from vibesensor.recording.raw_capture import RawCaptureChunk

_FRAME_SAMPLES = 200
_FRAME_US = 250_000  # 200 samples at 800 Hz


def _proof_state(tmp_path: Path, t0s_us: list[int]) -> str:
    store = HistoryRawCaptureStore(data_dir=tmp_path)
    samples = np.zeros((_FRAME_SAMPLES, 3), dtype=np.int16).tobytes(order="C")
    for t0_us in t0s_us:
        store.append_chunk(
            "run",
            RawCaptureChunk(
                client_id="sensor-a",
                sample_rate_hz=800,
                t0_us=t0_us,
                sample_count=_FRAME_SAMPLES,
                samples_i16le=samples,
            ),
        )
    manifest = store.finalize_run("run")
    assert manifest is not None
    sensor = manifest.sensor_manifest("sensor-a")
    assert sensor is not None
    return sensor.sample_rate_proof_state


def _contiguous(count: int) -> list[int]:
    return [1_000_000 + index * _FRAME_US for index in range(count)]


@pytest.mark.parametrize(
    ("label", "t0s_us"),
    [
        ("contiguous", _contiguous(40)),
        ("dropped chunk", _contiguous(20) + _contiguous(41)[21:]),
        ("clock step back", _contiguous(20) + [t0 - 6_000 for t0 in _contiguous(40)[20:]]),
        ("clock step forward", _contiguous(20) + [t0 + 6_000 for t0 in _contiguous(40)[20:]]),
        ("reordered chunk", (lambda t: t[:10] + [t[11], t[10]] + t[12:])(_contiguous(40))),
    ],
)
def test_isolated_timing_breaks_keep_the_observed_rate(
    tmp_path: Path, label: str, t0s_us: list[int]
) -> None:
    assert _proof_state(tmp_path, t0s_us) == "observed_consistent", label


def test_widespread_timing_breaks_leave_the_rate_unverified(tmp_path: Path) -> None:
    jittered = [t0 + (6_000 if index % 3 == 0 else 0) for index, t0 in enumerate(_contiguous(40))]

    assert _proof_state(tmp_path, jittered) == "timing_inconsistent"
