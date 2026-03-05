"""Runtime quality-pass regressions (issues 19–24).

Covers:
  19 – bad-client diagnostics skip (live_diagnostics)
  20 – ring buffer wraparound (processing)
  21 – _bounded_sample edge cases (api)
  22 – speed_unit persistence (settings_store)
  23 – iter_run_samples pagination correctness (history_db)
  24 – schema v2→v3 migration (history_db)
"""

from __future__ import annotations

from math import pi
from pathlib import Path

import numpy as np
import pytest

from vibesensor.api import _bounded_sample
from vibesensor.history_db import HistoryDB


def _make_history_db(tmp_path: Path, name: str = "history.db") -> HistoryDB:
    return HistoryDB(tmp_path / name)


def _seeded_history_db(
    tmp_path: Path, run_id: str, n_samples: int, *, name: str = "history.db"
) -> HistoryDB:
    """Create a HistoryDB with one run containing *n_samples* rows."""
    db = _make_history_db(tmp_path, name)
    db.create_run(run_id, "2026-01-01T00:00:00Z", {"src": "test"})
    db.append_samples(run_id, [{"i": i} for i in range(n_samples)])
    return db


def _make_tone_chunk(freq_hz: float, n_samples: int, sample_rate_hz: int) -> np.ndarray:
    """Return an (N, 3) float32 chunk with a sine tone on the X axis."""
    t = np.arange(n_samples, dtype=np.float64) / sample_rate_hz
    x = (0.5 * np.sin(2 * pi * freq_hz * t)).astype(np.float32)
    zeros = np.zeros_like(x)
    return np.stack([x, zeros, zeros], axis=1)


class TestBoundedSample:
    @pytest.mark.parametrize(
        "n_items, max_items, total_hint, exp_total, exp_len, exp_stride",
        [
            pytest.param(5, 100, None, 5, 5, 1, id="small_input_no_halving"),
            pytest.param(10, 10, None, 10, 10, None, id="exact_limit"),
            pytest.param(0, 10, None, 0, 0, None, id="empty_input"),
        ],
    )
    def test_bounded_sample_basic(
        self,
        n_items: int,
        max_items: int,
        total_hint: int | None,
        exp_total: int,
        exp_len: int,
        exp_stride: int | None,
    ) -> None:
        items = [{"i": i} for i in range(n_items)]
        kwargs: dict = {"max_items": max_items}
        if total_hint is not None:
            kwargs["total_hint"] = total_hint
        kept, total, stride = _bounded_sample(iter(items), **kwargs)
        assert total == exp_total
        assert len(kept) == exp_len
        if exp_stride is not None:
            assert stride == exp_stride

    def test_halving_reduces_count(self) -> None:
        items = [{"i": i} for i in range(200)]
        kept, total, stride = _bounded_sample(iter(items), max_items=50)
        assert total == 200
        assert len(kept) <= 50
        assert stride > 1

    def test_total_hint_avoids_halving(self) -> None:
        """With total_hint provided, stride is pre-computed."""
        items = [{"i": i} for i in range(200)]
        kept, total, stride = _bounded_sample(iter(items), max_items=50, total_hint=200)
        assert total == 200
        assert stride == 4
        assert len(kept) == 50
