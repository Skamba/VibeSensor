"""Analysis pipeline integration regressions.

Each test is tagged with the fix number it validates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vibesensor.analysis import summarize_run_data
from vibesensor.history_db import HistoryDB
from vibesensor.runlog import bounded_sample

_START = "2026-01-01T00:00:00Z"

_END = "2026-01-01T00:05:00Z"


@pytest.fixture()
def db(tmp_path: Path) -> HistoryDB:
    return HistoryDB(tmp_path / "pipeline_test.db")


def _simple_metadata(run_id: str = "test-run", lang: str = "en") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "start_time_utc": _START,
        "end_time_utc": _END,
        "sensor_model": "ADXL345",
        "language": lang,
    }


def _simple_samples(n: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "t_s": float(i),
            "speed_kmh": 60.0 + i,
            "vibration_strength_db": 25.0 + i * 0.5,
            "accel_x_g": 0.01 * i,
            "accel_y_g": 0.02 * i,
            "accel_z_g": 1.0 + 0.005 * i,
            "client_id": "sensor_a",
            "location": "Front Left",
        }
        for i in range(n)
    ]


def _summarize(**overrides: Any) -> dict[str, Any]:
    """Shortcut: summarize_run_data with sensible defaults."""
    kw: dict[str, Any] = {"include_samples": False}
    kw.update(overrides)
    meta = kw.pop("metadata", _simple_metadata())
    samples = kw.pop("samples", _simple_samples())
    return summarize_run_data(meta, samples, **kw)


def _setup_stale_pair(db: HistoryDB) -> None:
    """Shared setup: r1 finalized (analyzing), r2 still recording."""
    db.create_run("r1", _START, {})
    db.finalize_run("r1", _END)
    db.create_run("r2", "2026-01-01T00:10:00Z", {})


class TestBoundedSample:
    """Fix 1: The canonical bounded_sample lives in runlog, not duplicated."""

    @pytest.mark.parametrize(
        "n, max_items, total_hint, expect_total, expect_max_len",
        [
            pytest.param(100, 20, None, 100, 20, id="downsampling"),
            pytest.param(5, 100, None, 5, 5, id="below-limit"),
            pytest.param(1000, 50, 1000, 1000, 50, id="total-hint"),
            pytest.param(0, 10, None, 0, 0, id="empty"),
        ],
    )
    def test_bounded_sample(
        self,
        n: int,
        max_items: int,
        total_hint: int | None,
        expect_total: int,
        expect_max_len: int,
    ) -> None:
        items = [{"i": i} for i in range(n)]
        kwargs: dict[str, Any] = {"max_items": max_items}
        if total_hint is not None:
            kwargs["total_hint"] = total_hint
        kept, total, stride = bounded_sample(iter(items), **kwargs)
        assert total == expect_total
        assert len(kept) <= expect_max_len
        assert stride >= 1
