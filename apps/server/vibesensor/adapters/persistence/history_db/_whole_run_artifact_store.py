"""File-backed whole-run artifact sidecar store for dense post-analysis outputs."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from threading import RLock

from vibesensor.shared.json_utils import safe_json_dumps
from vibesensor.shared.types.whole_run_analysis import (
    WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME,
    WholeRunArtifactManifest,
)

_MANIFEST_FILE_NAME = "manifest.json"


class HistoryWholeRunArtifactStore:
    """Store dense whole-run artifacts in deterministic per-run directories."""

    __slots__ = ("_base_dir", "_data_dir", "_lock")

    def __init__(self, *, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._base_dir = data_dir / WHOLE_RUN_ARTIFACT_STORAGE_DIR_NAME
        self._lock = RLock()

    def store_run(
        self,
        manifest: WholeRunArtifactManifest,
        *,
        artifact_contents: Mapping[str, bytes],
    ) -> WholeRunArtifactManifest:
        run_dir = self._data_dir / manifest.relative_dir
        with self._lock:
            if run_dir.exists():
                shutil.rmtree(run_dir)
            missing = [
                artifact.artifact_key
                for artifact in manifest.artifacts
                if artifact.artifact_key not in artifact_contents
            ]
            if missing:
                raise ValueError(
                    "whole-run artifact store missing contents for keys: "
                    + ", ".join(sorted(missing))
                )
            run_dir.mkdir(parents=True, exist_ok=True)
            for artifact in manifest.artifacts:
                artifact_path = run_dir / artifact.relative_path
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                artifact_path.write_bytes(bytes(artifact_contents[artifact.artifact_key]))
            (run_dir / _MANIFEST_FILE_NAME).write_text(
                safe_json_dumps(manifest.to_json_object()),
                encoding="utf-8",
            )
        return manifest

    def load_artifact_bytes(
        self,
        manifest: WholeRunArtifactManifest,
        *,
        artifact_key: str,
    ) -> bytes | None:
        artifact = manifest.artifact(artifact_key)
        if artifact is None:
            return None
        artifact_path = self._data_dir / manifest.relative_dir / artifact.relative_path
        if not artifact_path.exists():
            return None
        return artifact_path.read_bytes()

    def delete_run_artifacts(self, run_id: str) -> None:
        with self._lock:
            shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def run_dir(self, run_id: str) -> Path:
        return self._base_dir / run_id
