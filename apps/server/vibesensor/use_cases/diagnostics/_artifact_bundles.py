"""Shared helpers for compact whole-run artifact bundle construction."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowPolicy,
)


@dataclass(frozen=True, slots=True)
class SingleArtifactBundleParts:
    manifest: WholeRunArtifactManifest
    artifact_contents: dict[str, bytes]


def build_single_artifact_bundle_parts(
    *,
    artifact_key: str,
    relative_path: str,
    file_format: str,
    record_count: int,
    content_bytes: bytes,
    created_at: str,
    source_manifest: WholeRunArtifactManifest | None = None,
    run_id: str | None = None,
    relative_dir: str | None = None,
    window_policy: WholeRunWindowPolicy | None = None,
    total_window_count: int | None = None,
    sensor_id: str | None = None,
) -> SingleArtifactBundleParts:
    artifact = WholeRunArtifactFile(
        artifact_key=artifact_key,
        relative_path=relative_path,
        file_format=file_format,
        record_count=record_count,
        sensor_id=sensor_id,
    )
    resolved_run_id = run_id
    resolved_relative_dir = relative_dir
    resolved_window_policy = window_policy
    resolved_total_window_count = total_window_count
    if source_manifest is not None:
        if resolved_run_id is None:
            resolved_run_id = source_manifest.run_id
        if resolved_relative_dir is None:
            resolved_relative_dir = source_manifest.relative_dir
        if resolved_window_policy is None:
            resolved_window_policy = source_manifest.window_policy
        if resolved_total_window_count is None:
            resolved_total_window_count = source_manifest.total_window_count
    if (
        resolved_run_id is None
        or resolved_relative_dir is None
        or resolved_window_policy is None
        or resolved_total_window_count is None
    ):
        raise ValueError(
            "single-artifact bundle helper requires complete manifest fields before construction"
        )
    if source_manifest is not None:
        manifest = WholeRunArtifactManifest(
            run_id=resolved_run_id,
            relative_dir=resolved_relative_dir,
            window_policy=resolved_window_policy,
            total_window_count=resolved_total_window_count,
            artifacts=(artifact,),
            created_at=created_at,
            schema_version=source_manifest.schema_version,
            storage_type=source_manifest.storage_type,
            algorithm_versions=dict(source_manifest.algorithm_versions),
            configuration=dict(source_manifest.configuration),
            source_raw_manifests=source_manifest.source_raw_manifests,
        )
    else:
        manifest = WholeRunArtifactManifest(
            run_id=resolved_run_id,
            relative_dir=resolved_relative_dir,
            window_policy=resolved_window_policy,
            total_window_count=resolved_total_window_count,
            artifacts=(artifact,),
            created_at=created_at,
        )
    return SingleArtifactBundleParts(
        manifest=manifest,
        artifact_contents={artifact_key: content_bytes},
    )
