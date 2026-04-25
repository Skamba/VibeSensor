from __future__ import annotations

import pytest

from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.run.post_analysis_whole_run_builders import (
    StoredWholeRunArtifactBundle,
    merge_whole_run_artifact_bundles,
)


def _window_policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=800,
        window_size_samples=2048,
        stride_samples=200,
        overlap_samples=1848,
        feature_interval_s=0.25,
    )


def _bundle(*, artifact_key: str, relative_path: str) -> StoredWholeRunArtifactBundle:
    manifest = WholeRunArtifactManifest(
        run_id="run-1",
        relative_dir="whole-run-artifacts/run-1",
        window_policy=_window_policy(),
        total_window_count=4,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key=artifact_key,
                relative_path=relative_path,
                file_format="jsonl",
                record_count=4,
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )
    return StoredWholeRunArtifactBundle(
        manifest=manifest,
        artifact_contents={artifact_key: artifact_key.encode("utf-8")},
    )


def test_merge_whole_run_artifact_bundles_combines_manifests_and_bytes() -> None:
    merged = merge_whole_run_artifact_bundles(
        _bundle(artifact_key="spectral-summary:sensor-a", relative_path="spectra/a.jsonl"),
        _bundle(artifact_key="context-labels", relative_path="context/labels.jsonl"),
    )

    assert merged is not None
    assert [artifact.artifact_key for artifact in merged.manifest.artifacts] == [
        "spectral-summary:sensor-a",
        "context-labels",
    ]
    assert merged.artifact_contents == {
        "spectral-summary:sensor-a": b"spectral-summary:sensor-a",
        "context-labels": b"context-labels",
    }


def test_merge_whole_run_artifact_bundles_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="must not reuse artifact keys"):
        merge_whole_run_artifact_bundles(
            _bundle(artifact_key="shared", relative_path="first.jsonl"),
            _bundle(artifact_key="shared", relative_path="second.jsonl"),
        )
