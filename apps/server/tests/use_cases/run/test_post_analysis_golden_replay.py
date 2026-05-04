from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_support.golden_replay import (
    GoldenReplayFixture,
    execute_golden_replay_fixture,
    golden_replay_fixtures,
    write_golden_replay_snapshot,
)


@pytest.mark.parametrize(
    "fixture",
    golden_replay_fixtures(fast_ci_only=True),
    ids=lambda fixture: fixture.case_id,
)
def test_post_analysis_golden_replay_fast_subset(
    fixture: GoldenReplayFixture,
    tmp_path: Path,
) -> None:
    result = execute_golden_replay_fixture(fixture)
    snapshot_path = write_golden_replay_snapshot(
        result=result,
        output_dir=tmp_path / "golden-replay-artifacts",
    )

    assert snapshot_path.exists()
    metadata = result.analysis.get("analysis_metadata")
    assert isinstance(metadata, dict)
    assert metadata["whole_run_artifacts_available"] is True
    assert metadata["whole_run_context_available"] is True
    assert result.manifest.total_window_count > 0
    assert result.manifest.source_raw_manifests
    assert result.manifest.algorithm_versions
    assert result.manifest.generated_artifact_paths
    _assert_expected_outcome(fixture, result.analysis)


def test_golden_replay_fixture_catalog_covers_required_scenarios() -> None:
    fixtures = golden_replay_fixtures()

    assert [fixture.case_id for fixture in fixtures] == [
        "balanced-no-issue",
        "front-wheel-imbalance",
        "rear-wheel-imbalance",
        "driveshaft-rumble",
        "engine-harmonic",
        "transient-spike",
        "noisy-sensor",
        "gps-dropout",
        "missing-rpm",
    ]
    assert all(fixture.seed > 0 for fixture in fixtures)
    assert all(fixture.expected.tolerance_bands is not None for fixture in fixtures)


def _assert_expected_outcome(
    fixture: GoldenReplayFixture,
    analysis: dict[str, object],
) -> None:
    top = _top_cause(analysis)
    expected = fixture.expected
    if expected.suspected_source is not None:
        assert top is not None
        assert top.get("suspected_source") == expected.suspected_source
        if expected.strongest_location is not None:
            assert top.get("strongest_location") == expected.strongest_location
        confidence = float(top.get("confidence", 0.0))
        assert expected.confidence_range[0] <= confidence <= expected.confidence_range[1]
    elif top is not None and expected.max_false_positive_confidence is not None:
        assert float(top.get("confidence", 0.0)) <= expected.max_false_positive_confidence

    metadata = analysis.get("analysis_metadata")
    assert isinstance(metadata, dict)
    for reason in expected.unavailable_reasons:
        if reason == "missing_speed":
            assert int(metadata.get("whole_run_context_missing_speed_window_count", 0)) > 0
        if reason == "missing_rpm":
            assert int(metadata.get("whole_run_context_missing_rpm_window_count", 0)) > 0


def _top_cause(analysis: dict[str, object]) -> dict[str, Any] | None:
    top_causes = analysis.get("top_causes")
    if not isinstance(top_causes, list) or not top_causes:
        return None
    top = top_causes[0]
    assert isinstance(top, dict)
    return top
