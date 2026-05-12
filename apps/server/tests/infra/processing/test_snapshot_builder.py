"""Tests for snapshot window sizing."""

from __future__ import annotations

import pytest

from vibesensor.infra.processing.snapshot_builder import (
    SnapshotWindow,
    compute_snapshot_window,
)

_DEFAULT_WINDOW_KWARGS = {
    "count": 1000,
    "capacity": 2000,
    "sample_rate_hz": 200,
    "waveform_seconds": 2,
    "fft_n": 256,
}


def _snapshot_window(**overrides: int) -> SnapshotWindow:
    return compute_snapshot_window(**{**_DEFAULT_WINDOW_KWARGS, **overrides})


class TestComputeSnapshotWindow:
    """Exercise snapshot-window sizing and whether a separate FFT block is needed."""

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            pytest.param({}, SnapshotWindow(400, False), id="default-time-window"),
            pytest.param({"count": 50}, SnapshotWindow(50, False), id="count-limits-window"),
            pytest.param(
                {"count": 500, "capacity": 100},
                SnapshotWindow(100, True),
                id="capacity-limits-window-and-requires-fft",
            ),
            pytest.param(
                {"count": 512, "capacity": 512, "sample_rate_hz": 100, "waveform_seconds": 1},
                SnapshotWindow(100, True),
                id="separate-fft-for-small-time-window",
            ),
            pytest.param(
                {"count": 512, "capacity": 512, "sample_rate_hz": 10},
                SnapshotWindow(20, True),
                id="separate-fft-for-low-rate-large-count",
            ),
            pytest.param(
                {"capacity": 1000}, SnapshotWindow(400, False), id="time-window-covers-fft"
            ),
            pytest.param(
                {"count": 100, "capacity": 1000, "sample_rate_hz": 10},
                SnapshotWindow(20, False),
                id="small-count-skips-separate-fft",
            ),
        ],
    )
    def test_window_contract(self, overrides: dict[str, int], expected: SnapshotWindow) -> None:
        assert _snapshot_window(**overrides) == expected

    def test_minimum_window_is_one(self) -> None:
        result = _snapshot_window(
            count=5,
            capacity=100,
            sample_rate_hz=1,
            waveform_seconds=0,
        )
        assert result.n_time >= 1
