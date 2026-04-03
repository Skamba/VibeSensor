"""Rollback snapshot creation for updater-managed server wheels."""

from __future__ import annotations

import tempfile
from pathlib import Path

from vibesensor.use_cases.updates.artifact_validation import wheel_metadata_validation_errors
from vibesensor.use_cases.updates.rollback_snapshot import (
    RollbackSnapshotMetadata,
    RollbackSnapshotStore,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.venv_paths import reinstall_python_executable


class RollbackSnapshotBuilder:
    """Capture the current server wheel into rollback storage before mutation."""

    __slots__ = ("_commands", "_repo", "_rollback_dir", "_rollback_snapshots", "_tracker")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        repo: Path,
        rollback_dir: Path,
        rollback_snapshots: RollbackSnapshotStore,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._repo = repo
        self._rollback_dir = rollback_dir
        self._rollback_snapshots = rollback_snapshots

    def _existing_local_rollback_wheel(self, *, current_version: str) -> Path | None:
        candidates = sorted(
            self._rollback_dir.glob(f"vibesensor-{current_version}-*.whl"),
            reverse=True,
        )
        for candidate in candidates:
            errors = wheel_metadata_validation_errors(
                candidate,
                expected_name="vibesensor",
                expected_version=current_version,
            )
            if not errors:
                self._tracker.log(
                    f"Reusing existing local rollback wheel {candidate.name}",
                )
                return candidate
            self._tracker.log(
                f"Ignoring existing rollback wheel {candidate.name}: {'; '.join(errors)}",
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
            self._tracker.log(
                f"{source_label} produced unusable wheel {rollback_wheel.name}: "
                f"{'; '.join(errors)}",
            )
        self._tracker.log(
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
            self._tracker.log(
                f"Local rollback wheel build skipped: {package_dir / 'pyproject.toml'} not found",
            )
            return None
        rc, _, stderr = await self._commands.run(
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
        if rc != 0:
            self._tracker.log(
                "Local rollback wheel build failed "
                f"(exit {rc}); falling back to package-index download: {stderr}",
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
        rc, _, stderr = await self._commands.run(
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
        if rc != 0:
            self._tracker.log(
                f"Package-index rollback download failed (exit {rc}): {stderr}",
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
    ) -> bool:
        from vibesensor.use_cases.updates.artifact_validation import sha256_file

        rollback_sha256 = sha256_file(rollback_wheel)
        promoted_wheel = self._rollback_dir / rollback_wheel.name
        if rollback_wheel != promoted_wheel:
            rollback_wheel.replace(promoted_wheel)
        try:
            self._rollback_snapshots.write_metadata(
                RollbackSnapshotMetadata(
                    version=current_version,
                    wheel_name=promoted_wheel.name,
                    sha256=rollback_sha256,
                ),
            )
        except OSError as exc:
            self._tracker.add_issue(
                "installing",
                "Rollback metadata could not be written",
                str(exc),
            )
            return False
        self._rollback_snapshots.prune_wheels(keep_name=promoted_wheel.name)
        self._tracker.log(
            "Rollback snapshot created successfully "
            f"(wheel={promoted_wheel.name}, sha256={rollback_sha256})",
        )
        return True

    async def snapshot_for_rollback(self) -> bool:
        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        venv_python = reinstall_python_executable(self._repo)
        from vibesensor import __version__ as current_version

        self._tracker.log(f"Creating rollback snapshot (version={current_version})")
        if existing_wheel := self._existing_local_rollback_wheel(current_version=current_version):
            return self._write_rollback_snapshot(
                rollback_wheel=existing_wheel,
                current_version=current_version,
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
                (self._rollback_dir / "rollback_version.txt").write_text(
                    current_version,
                    encoding="utf-8",
                )
                return False
            return self._write_rollback_snapshot(
                rollback_wheel=rollback_wheel,
                current_version=current_version,
            )
