from __future__ import annotations

import json
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
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["case_id"] == fixture.case_id
    assert snapshot["expected"]["suspected_source"] == fixture.expected.suspected_source
    assert snapshot["artifact_paths"] == result.manifest.generated_artifact_paths
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
        "fixed-resonance-speed-sweep",
        "road-shock-transient",
        "transient-spike",
        "noisy-sensor",
        "gps-dropout",
        "missing-rpm",
    ]
    assert {fixture.group for fixture in fixtures} >= {
        "baseline",
        "wheel",
        "driveline",
        "engine",
        "resonance",
        "road_shock",
    }
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
        if expected.confidence_label_key is not None:
            assert top.get("confidence_label_key") == expected.confidence_label_key
    elif top is not None and expected.max_false_positive_confidence is not None:
        assert float(top.get("confidence", 0.0)) <= expected.max_false_positive_confidence
    else:
        assert expected.confidence_range[0] <= 0.0 <= expected.confidence_range[1]

    _assert_tolerance_bands(fixture, analysis, top)
    _assert_required_warnings(fixture, analysis)
    _assert_required_metadata(fixture, analysis)

    metadata = analysis.get("analysis_metadata")
    assert isinstance(metadata, dict)
    for reason in expected.unavailable_reasons:
        if reason == "missing_speed":
            assert int(metadata.get("whole_run_context_missing_speed_window_count", 0)) > 0
        if reason == "missing_rpm":
            assert int(metadata.get("whole_run_context_missing_rpm_window_count", 0)) > 0


def _assert_tolerance_bands(
    fixture: GoldenReplayFixture,
    analysis: dict[str, object],
    top: dict[str, Any] | None,
) -> None:
    bands = fixture.expected.tolerance_bands or {}
    for metric, (minimum, maximum) in bands.items():
        if metric == "top_confidence":
            value = float(top.get("confidence", 0.0)) if top is not None else 0.0
        elif metric == "frequency_hz":
            assert top is not None
            value = _representative_matched_frequency_hz(top)
        elif metric == "fixed_frequency_hz":
            assert fixture.primary_frequency_hz is not None
            value = fixture.primary_frequency_hz
        elif metric == "missing_speed_windows_min":
            metadata = analysis.get("analysis_metadata")
            assert isinstance(metadata, dict)
            value = float(metadata.get("whole_run_context_missing_speed_window_count", 0.0))
        elif metric == "missing_rpm_windows_min":
            metadata = analysis.get("analysis_metadata")
            assert isinstance(metadata, dict)
            value = float(metadata.get("whole_run_context_missing_rpm_window_count", 0.0))
        else:
            metadata = analysis.get("analysis_metadata")
            assert isinstance(metadata, dict)
            value = float(metadata.get(metric, 0.0))
        assert minimum <= value <= maximum, (
            f"{fixture.case_id} expected {metric} in [{minimum}, {maximum}], got {value}"
        )


def _assert_required_warnings(
    fixture: GoldenReplayFixture,
    analysis: dict[str, object],
) -> None:
    expected_codes = set(fixture.expected.required_warning_codes)
    if not expected_codes:
        return
    warnings = analysis.get("warnings")
    assert isinstance(warnings, list)
    actual_codes = {str(warning.get("code")) for warning in warnings if isinstance(warning, dict)}
    assert expected_codes <= actual_codes


def _assert_required_metadata(
    fixture: GoldenReplayFixture,
    analysis: dict[str, object],
) -> None:
    minimums = fixture.expected.required_metadata_minimums or {}
    if not minimums:
        return
    metadata = analysis.get("analysis_metadata")
    assert isinstance(metadata, dict)
    for key, minimum in minimums.items():
        assert float(metadata.get(key, 0.0)) >= minimum


def _representative_matched_frequency_hz(top: dict[str, Any]) -> float:
    points = top.get("matched_points")
    assert isinstance(points, list) and points
    frequencies = [
        float(point.get("matched_hz", 0.0))
        for point in points
        if isinstance(point, dict) and point.get("matched_hz") is not None
    ]
    assert frequencies
    return sum(frequencies) / len(frequencies)


def _top_cause(analysis: dict[str, object]) -> dict[str, Any] | None:
    top_causes = analysis.get("top_causes")
    if not isinstance(top_causes, list) or not top_causes:
        return None
    top = top_causes[0]
    assert isinstance(top, dict)
    return top
