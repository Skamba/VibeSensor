"""Rollback snapshot creation for updater-managed server wheels."""

from __future__ import annotations

import tempfile
from pathlib import Path

from vibesensor.use_cases.updates.artifact_validation import wheel_metadata_validation_errors
from vibesensor.use_cases.updates.models import UpdateRuntimeDetails
from vibesensor.use_cases.updates.rollback_snapshot import (
    RollbackSnapshotMetadata,
    RollbackSnapshotStore,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.status.runtime_details import collect_runtime_details
from vibesensor.use_cases.updates.venv_paths import reinstall_python_executable


class RollbackSnapshotBuilder:
    """Capture the current server wheel into rollback storage before mutation."""

    __slots__ = (
        "_commands",
        "_config_path",
        "_repo",
        "_rollback_dir",
        "_rollback_snapshots",
        "_status",
    )

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        repo: Path,
        rollback_dir: Path,
        rollback_snapshots: RollbackSnapshotStore,
        config_path: Path | None,
    ) -> None:
        self._commands = commands
        self._status = status
        self._repo = repo
        self._rollback_dir = rollback_dir
        self._rollback_snapshots = rollback_snapshots
        self._config_path = config_path

    def _existing_snapshot_wheel(self, *, current_version: str) -> Path | None:
        snapshot = self._rollback_snapshots.load_snapshot(report_issues=False)
        if snapshot is None:
            return None
        errors = wheel_metadata_validation_errors(
            snapshot.wheel_path,
            expected_name="vibesensor",
            expected_version=current_version,
        )
        if snapshot.metadata.version == current_version and not errors:
            self._status.log("Reusing existing rollback snapshot wheel")
            return snapshot.wheel_path
        if errors:
            self._status.log(
                f"Ignoring existing rollback snapshot wheel: {'; '.join(errors)}",
            )
        return None

    def _select_staged_rollback_wheel(
        self,
        *,
        stage_dir: Path,
        current_version: str,
        source_label: str,
    ) -> Path | None:
        staged_wheels = sorted(stage_dir.glob("vibesensor-*.whl"), reverse=True)
        for rollback_wheel in staged_wheels:
            errors = wheel_metadata_validation_errors(
                rollback_wheel,
                expected_name="vibesensor",
                expected_version=current_version,
            )
            if not errors:
                return rollback_wheel
            self._status.log(
                f"{source_label} produced unusable wheel {rollback_wheel.name}: "
                f"{'; '.join(errors)}",
            )
        self._status.log(
            f"{source_label} did not produce a usable wheel for {current_version}",
        )
        return None

    async def _build_local_rollback_wheel(
        self,
        *,
        current_version: str,
        stage_dir: Path,
        venv_python: str,
    ) -> Path | None:
        package_dir = self._repo / "apps" / "server"
        if not (package_dir / "pyproject.toml").is_file():
            self._status.log(
                f"Local rollback wheel build skipped: {package_dir / 'pyproject.toml'} not found",
            )
            return None
        result = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "-w",
                str(stage_dir),
                str(package_dir),
            ],
            phase="installing",
            timeout=60,
            sudo=False,
        )
        if result.returncode != 0:
            self._status.log(
                "Local rollback wheel build failed "
                f"(exit {result.returncode}); falling back to package-index download: "
                f"{result.stderr}",
            )
            return None
        return self._select_staged_rollback_wheel(
            stage_dir=stage_dir,
            current_version=current_version,
            source_label="Local rollback wheel build",
        )

    async def _download_rollback_wheel(
        self,
        *,
        current_version: str,
        stage_dir: Path,
        venv_python: str,
    ) -> Path | None:
        result = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--no-build-isolation",
                "-d",
                str(stage_dir),
                f"vibesensor=={current_version}",
            ],
            phase="installing",
            timeout=60,
            sudo=False,
        )
        if result.returncode != 0:
            self._status.log(
                f"Package-index rollback download failed (exit {result.returncode}): "
                f"{result.stderr}",
            )
            return None
        return self._select_staged_rollback_wheel(
            stage_dir=stage_dir,
            current_version=current_version,
            source_label="Package-index rollback download",
        )

    def _write_rollback_snapshot(
        self,
        *,
        rollback_wheel: Path,
        current_version: str,
        runtime_details: UpdateRuntimeDetails,
    ) -> bool:
        from vibesensor.use_cases.updates.artifact_validation import sha256_file

        rollback_sha256 = sha256_file(rollback_wheel)
        promotion = self._rollback_snapshots.replace_snapshot_wheel(rollback_wheel)
        try:
            self._rollback_snapshots.write_metadata(
                RollbackSnapshotMetadata(
                    version=current_version,
                    sha256=rollback_sha256,
                    config_path=str(self._config_path) if self._config_path else "",
                    repo_path=str(self._repo),
                    static_assets_hash=runtime_details.static_assets_hash,
                    static_build_source_hash=runtime_details.static_build_source_hash,
                    static_build_commit=runtime_details.static_build_commit,
                    assets_verified=runtime_details.assets_verified,
                    has_packaged_static=runtime_details.has_packaged_static,
                ),
            )
        except OSError as exc:
            self._rollback_snapshots.rollback_snapshot_wheel(promotion)
            self._status.add_issue(
                "installing",
                "Rollback metadata could not be written",
                str(exc),
            )
            return False
        self._rollback_snapshots.commit_snapshot_wheel(promotion)
        self._status.log(
            "Rollback snapshot created successfully "
            f"(version={current_version}, sha256={rollback_sha256})",
        )
        return True

    async def snapshot_for_rollback(self) -> bool:
        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        venv_python = reinstall_python_executable(self._repo)
        from vibesensor import __version__ as current_version

        runtime_details = collect_runtime_details(self._repo)

        self._status.log(f"Creating rollback snapshot (version={current_version})")
        if existing_wheel := self._existing_snapshot_wheel(current_version=current_version):
            return self._write_rollback_snapshot(
                rollback_wheel=existing_wheel,
                current_version=current_version,
                runtime_details=runtime_details,
            )
        with tempfile.TemporaryDirectory(
            prefix="vibesensor-rollback-stage-",
            dir=self._rollback_dir.parent,
        ) as stage_dir_text:
            stage_dir = Path(stage_dir_text)
            rollback_wheel = await self._build_local_rollback_wheel(
                current_version=current_version,
                stage_dir=stage_dir,
                venv_python=venv_python,
            )
            if rollback_wheel is None:
                rollback_wheel = await self._download_rollback_wheel(
                    current_version=current_version,
                    stage_dir=stage_dir,
                    venv_python=venv_python,
                )
            if rollback_wheel is None:
                return False
            return self._write_rollback_snapshot(
                rollback_wheel=rollback_wheel,
                current_version=current_version,
                runtime_details=runtime_details,
            )
