"""Golden replay snapshot helpers."""

from __future__ import annotations

import json
from pathlib import Path

from test_support.golden_replay_types import GoldenReplayExpected, GoldenReplayResult


def write_golden_replay_snapshot(
    *,
    result: GoldenReplayResult,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.fixture.case_id}.json"
    top_causes = result.analysis.get("top_causes")
    analysis_metadata = result.analysis.get("analysis_metadata")
    diagnosis_summaries = result.analysis.get("whole_run_diagnosis_summaries")
    path.write_text(
        json.dumps(
            {
                "case_id": result.fixture.case_id,
                "title": result.fixture.title,
                "seed": result.fixture.seed,
                "expected": _expected_snapshot(result.fixture.expected),
                "top_causes": top_causes if isinstance(top_causes, list) else [],
                "whole_run_diagnosis_summaries": (
                    diagnosis_summaries if isinstance(diagnosis_summaries, list) else []
                ),
                "analysis_metadata": (
                    analysis_metadata if isinstance(analysis_metadata, dict) else {}
                ),
                "artifact_keys": [artifact.artifact_key for artifact in result.manifest.artifacts],
                "artifact_paths": result.manifest.generated_artifact_paths,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _expected_snapshot(expected: GoldenReplayExpected) -> dict[str, object]:
    return {
        "suspected_source": expected.suspected_source,
        "strongest_location": expected.strongest_location,
        "confidence_range": list(expected.confidence_range),
        "confidence_label_key": expected.confidence_label_key,
        "unavailable_reasons": list(expected.unavailable_reasons),
        "tolerance_bands": dict(expected.tolerance_bands or {}),
        "max_false_positive_confidence": expected.max_false_positive_confidence,
        "required_warning_codes": list(expected.required_warning_codes),
        "required_metadata_minimums": dict(expected.required_metadata_minimums or {}),
    }
