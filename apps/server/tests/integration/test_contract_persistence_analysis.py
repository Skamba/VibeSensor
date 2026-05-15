"""Contract bridge tests: Persistence → Analysis boundary.

These tests validate that samples written to :class:`HistoryDB`, read back,
and then fed into ``summarize_run_data()`` produce valid analysis output.
They are fast (<5 s), deterministic, and run in standard CI so that schema
drift between persistence and analysis is caught early.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support import (
    ALL_WHEEL_SENSORS,
    make_fault_samples,
    make_noise_samples,
    standard_metadata,
)

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.adapters.persistence.history_db import (
    RunHistoryRepository,
    create_history_persistence_adapters,
)
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.sensor_frames import (
    sensor_frame_from_mapping,
    sensor_frame_to_json_object,
)

pytestmark = pytest.mark.smoke


def _create_populated_db(
    meta: dict,
    samples: list[dict],
) -> tuple[RunHistoryRepository, str]:
    """Create an in-memory DB with a run containing *samples*."""
    db = create_history_persistence_adapters(Path(":memory:")).run_repository
    run_id = "contract-test-run"
    db.create_run(
        run_id,
        start_time_utc="2025-01-01T00:00:00Z",
        metadata=run_metadata_from_mapping(
            {
                "run_id": run_id,
                "start_time_utc": "2025-01-01T00:00:00Z",
                **meta,
            }
        ),
    )
    db.append_samples(run_id, [sensor_frame_from_mapping(sample) for sample in samples])
    return db, run_id


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_persisted_samples_produce_valid_analysis():
    """Samples round-tripped through the DB must produce valid analysis."""
    meta = standard_metadata(language="en")
    samples = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS,
        n_samples=15,
        speed_kmh=60.0,
    )
    samples.extend(
        make_fault_samples(
            fault_sensor="front-left",
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=80.0,
            n_samples=15,
        )
    )

    db, run_id = _create_populated_db(meta, samples)
    read_back = db.get_run_samples(run_id)

    summary = summarize_run_data(
        meta,
        [sensor_frame_to_json_object(row) for row in read_back],
        lang="en",
    )

    assert "findings" in summary
    assert summary["rows"] > 0


def test_noise_only_round_trip():
    """A no-fault run round-tripped through the DB must still analyze cleanly."""
    meta = standard_metadata(language="en")
    samples = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS,
        n_samples=30,
        speed_kmh=60.0,
    )

    db, run_id = _create_populated_db(meta, samples)
    read_back = db.get_run_samples(run_id)

    summary = summarize_run_data(
        meta,
        [sensor_frame_to_json_object(row) for row in read_back],
        lang="en",
    )

    assert "findings" in summary
    assert summary["rows"] == len(samples)


def test_sample_count_preserved_through_db():
    """The DB must not silently drop or duplicate samples."""
    meta = standard_metadata(language="en")
    samples = make_noise_samples(
        sensors=ALL_WHEEL_SENSORS,
        n_samples=20,
        speed_kmh=60.0,
    )
    original_count = len(samples)

    db, run_id = _create_populated_db(meta, samples)
    read_back = db.get_run_samples(run_id)

    assert len(read_back) == original_count


def test_key_sample_fields_survive_persistence():
    """Critical sample fields must be preserved through write→read."""
    meta = standard_metadata(language="en")
    samples = make_noise_samples(
        sensors=["front-left"],
        n_samples=5,
        speed_kmh=70.0,
    )

    db, run_id = _create_populated_db(meta, samples)
    read_back = db.get_run_samples(run_id)

    required_fields = {"t_s", "speed_kmh", "client_name", "vibration_strength_db"}
    for expected, row in zip(samples, read_back, strict=True):
        payload = sensor_frame_to_json_object(row)
        for field in required_fields:
            assert field in payload, f"Missing field {field!r} after DB round-trip"
            assert payload[field] == expected[field]
