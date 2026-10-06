"""Post-analysis loading of long runs: rows are picked from a light pass, then decoded.

The loader reads a few columns of every stored row, chooses the rows to keep
(all of them, or evenly spaced rows plus the loudest row of each stretch past
the cap) and decodes only those. These tests hold the light pass to the
selection a full decode of every row gives.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from test_support.history_db_lifecycle import (
    build_history_db,
    create_analyzing_run,
    create_recording_run,
    run_samples,
)
from test_support.history_db_sql import execute_statements

from vibesensor.analysis import post_analysis_loader
from vibesensor.analysis.post_analysis_loader import (
    LoadedPostAnalysisRun,
    load_post_analysis_run,
)
from vibesensor.history.history_db import HistoryDB
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings


def _store_run(
    db: HistoryDB,
    run_id: str,
    rows: list[dict[str, object]],
    *,
    raw_rows: tuple[tuple[str, tuple[object, ...]], ...] = (),
) -> None:
    metadata = create_recording_run(db, run_id)
    db.append_samples(run_id, sensor_frames_from_mappings(rows))
    if raw_rows:
        execute_statements(db, *raw_rows)
        db.append_samples(run_id, sensor_frames_from_mappings([{"t_s": 4.0}]))
    db.finalize_run(run_id, "2026-01-01T00:01:00Z", metadata=metadata)


def _loaded(db: HistoryDB, run_id: str) -> LoadedPostAnalysisRun:
    result = load_post_analysis_run(run_id=run_id, db=db)
    assert isinstance(result, LoadedPostAnalysisRun)
    return result


def test_long_runs_keep_loud_events_when_thinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(post_analysis_loader, "_MAX_POST_ANALYSIS_SAMPLES", 2)
    db = build_history_db(tmp_path)
    _store_run(
        db,
        "run-capped",
        [
            {"t_s": 1.0, "vibration_strength_db": 10.0},
            {"t_s": 2.0, "vibration_strength_db": 11.0},
            {"t_s": 3.0, "vibration_strength_db": 48.0},
            {"t_s": 4.0, "vibration_strength_db": 12.0},
        ],
    )

    result = _loaded(db, "run-capped")

    assert result.total_summary_row_count == 4
    assert result.summary_duration_s == pytest.approx(3.0)
    assert result.stride == 2
    assert result.sampling_method == "event_preserving"
    assert result.event_sample_count == 1
    assert [sample.t_s for sample in result.samples] == [1.0, 3.0]


def _varied_row(index: int) -> dict[str, object]:
    """Rows whose loudness ties, goes missing or hides in the peak list."""
    row: dict[str, object] = {"t_s": 0.25 * index, "client_id": f"s{index % 3}"}
    if index % 7:
        row["vibration_strength_db"] = float((index * 37) % 11)
    if index % 5 == 0:
        row["strength_peak_amp_g"] = 0.001 * ((index * 13) % 9)
    if index % 4:
        row["top_peaks"] = [
            {"hz": 10.0 + index % 50, "amp": 0.0001 * ((index * 7) % 23)},
            {"hz": 0.0, "amp": 9.0},  # invalid peak: ignored by the decode
        ]
    return row


def _full_decode_event_score(sample: SensorFrame) -> tuple[float, float, float]:
    """The loudness ranking a fully decoded row gets."""
    return (
        sample.vibration_strength_db if sample.vibration_strength_db is not None else -math.inf,
        sample.strength_peak_amp_g if sample.strength_peak_amp_g is not None else -math.inf,
        max((peak.amp for peak in sample.top_peaks), default=-math.inf),
    )


def test_light_pass_picks_the_rows_a_full_decode_would(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cap = 40
    monkeypatch.setattr(post_analysis_loader, "_MAX_POST_ANALYSIS_SAMPLES", cap)
    db = build_history_db(tmp_path)
    _store_run(db, "run-long", [_varied_row(index) for index in range(1, 301)])
    every_row = run_samples(db, "run-long")

    # The light pass ranks every row exactly as a full decode of the row does ...
    columns = db.run_sample_selection_columns("run-long")
    assert columns.row_id.tolist() == sorted(columns.row_id.tolist())
    assert post_analysis_loader._event_scores(columns) == [
        _full_decode_event_score(sample) for sample in every_row
    ]

    # ... and only the chosen rows are decoded.
    result = _loaded(db, "run-long")
    selection = post_analysis_loader._select_post_analysis_rows(columns)
    assert len(result.samples) == cap
    assert result.samples == [every_row[index] for index in selection.indices]
    assert result.sampling_method == "event_preserving"
    assert result.event_sample_count == selection.event_sample_count > 0
    assert result.summary_duration_s == pytest.approx(0.25 * 299)


def test_a_run_under_the_cap_loads_every_row_in_order(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    _store_run(db, "run-short", [_varied_row(index) for index in range(1, 51)])

    result = _loaded(db, "run-short")

    assert result.sampling_method == "full"
    assert result.stride == 1
    assert result.samples == run_samples(db, "run-short")


def test_corrupt_rows_are_skipped(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    _store_run(
        db,
        "run-corrupt",
        [{"t_s": 1.0}, {"t_s": 2.0}],
        raw_rows=(
            # Corrupt in a column the light pass reads ...
            ("INSERT INTO samples_v2 (run_id, top_peaks) VALUES (?, ?)", ("run-corrupt", "{bad")),
            # ... and in one only the full decode reads.
            (
                "INSERT INTO samples_v2 (run_id, t_s, sample_rate_hz) VALUES (?, ?, ?)",
                ("run-corrupt", 3.0, "not-a-rate"),
            ),
        ),
    )

    result = _loaded(db, "run-corrupt")

    assert [sample.t_s for sample in result.samples] == [1.0, 2.0, 4.0]


def test_a_run_without_rows_is_reported_empty(tmp_path: Path) -> None:
    db = build_history_db(tmp_path)
    create_analyzing_run(db, "run-empty")

    result = load_post_analysis_run(run_id="run-empty", db=db)

    assert not isinstance(result, LoadedPostAnalysisRun)
    assert result.error_message == "No samples collected during run"
