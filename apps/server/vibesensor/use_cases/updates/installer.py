"""Local install and rollback orchestration for updater runs."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.artifact_validation import WheelArtifactValidator, sha256_file
from vibesensor.use_cases.updates.rollback_snapshot import (
    RollbackSnapshotMetadata,
    RollbackSnapshotStore,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.venv_paths import reinstall_python_executable


@dataclass(frozen=True, slots=True)
class UpdateInstallerConfig:
    repo: Path
    rollback_dir: Path
    reinstall_timeout_s: float
    firmware_refresh_timeout_s: float


class UpdateInstaller:
    """Owns install, rollback snapshot orchestration, and rollback execution."""

    __slots__ = ("_commands", "_config", "_rollback_snapshots", "_tracker", "_wheel_validator")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateInstallerConfig,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._config = config
        self._rollback_snapshots = RollbackSnapshotStore(config.rollback_dir, tracker)
        self._wheel_validator = WheelArtifactValidator(tracker)

    async def snapshot_for_rollback(self) -> bool:
        self._config.rollback_dir.mkdir(parents=True, exist_ok=True)
        venv_python = reinstall_python_executable(self._config.repo)
        from vibesensor import __version__ as current_version

        self._tracker.log(f"Creating rollback snapshot (version={current_version})")
        with tempfile.TemporaryDirectory(
            prefix="vibesensor-rollback-stage-",
            dir=self._config.rollback_dir.parent,
        ) as stage_dir_text:
            stage_dir = Path(stage_dir_text)
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
                self._tracker.log(f"pip download for rollback failed (exit {rc}): {stderr}")
                (self._config.rollback_dir / "rollback_version.txt").write_text(
                    current_version,
                    encoding="utf-8",
                )
                return False
            staged_wheels = sorted(stage_dir.glob("vibesensor-*.whl"), reverse=True)
            if not staged_wheels:
                self._tracker.add_issue(
                    "installing",
                    "Rollback snapshot did not produce a wheel",
                    f"Expected vibesensor=={current_version} in {stage_dir}",
                )
                return False
            rollback_wheel = staged_wheels[0]
            if not self._wheel_validator.validate_wheel(
                rollback_wheel,
                phase="installing",
                context="Rollback snapshot wheel",
                fatal=False,
            ):
                return False
            rollback_sha256 = sha256_file(rollback_wheel)
            promoted_wheel = self._config.rollback_dir / rollback_wheel.name
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

    async def install_release(self, wheel_path: Path, expected_version: str) -> bool:
        if not self._wheel_validator.validate_wheel(
            wheel_path,
            phase="installing",
            context="Downloaded wheel",
            fatal=True,
        ):
            return False
        venv_python = reinstall_python_executable(self._config.repo)
        rc, _, stderr = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(wheel_path),
            ],
            phase="installing",
            timeout=self._config.reinstall_timeout_s,
            sudo=False,
        )
        if rc != 0:
            self._tracker.fail("installing", f"Wheel install failed (exit {rc})", stderr)
            self._tracker.log("Attempting rollback...")
            await self.rollback()
            return False

        installed_version = await self._verify_installed_version(phase="installing")
        if installed_version is None:
            self._tracker.log("Attempting rollback...")
            await self.rollback()
            return False

        self._tracker.log(f"Installed vibesensor {expected_version}")
        self._tracker.log(f"Verified installed version: {installed_version}")
        return True

    async def rollback(self) -> bool:
        self._tracker.log("Rolling back to previous version...")
        metadata = self._rollback_snapshots.load_metadata()
        rollback_wheels = self._rollback_snapshots.rollback_wheels()
        if not rollback_wheels:
            self._tracker.add_issue("installing", "No rollback wheel available")
            return False

        wheel: Path
        expected_version = ""
        expected_sha256: str | None = None
        if metadata is not None:
            wheel = self._config.rollback_dir / metadata.wheel_name
            expected_version = metadata.version
            expected_sha256 = metadata.sha256
            if not wheel.is_file():
                self._tracker.add_issue(
                    "installing",
                    "Rollback snapshot wheel is missing",
                    f"metadata expected {wheel}",
                )
                return False
        else:
            wheel = rollback_wheels[0]
            wheel_parts = wheel.stem.split("-")
            expected_version = wheel_parts[1] if len(wheel_parts) >= 2 else ""
            self._tracker.log(
                "Rollback metadata missing; falling back to newest "
                "rollback wheel without checksum pin",
            )

        if not self._wheel_validator.validate_wheel(
            wheel,
            phase="installing",
            context="Rollback wheel",
            fatal=False,
            expected_sha256=expected_sha256,
        ):
            return False

        venv_python = reinstall_python_executable(self._config.repo)
        rc, _, stderr = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(wheel),
            ],
            phase="installing",
            timeout=self._config.reinstall_timeout_s,
            sudo=False,
        )
        if rc != 0:
            self._tracker.add_issue(
                "installing",
                f"Rollback install failed (exit {rc})",
                stderr,
            )
            return False

        rolled_back_version = await self._verify_installed_version(phase="installing")
        if rolled_back_version is None:
            return False

        if expected_version and rolled_back_version != expected_version:
            self._tracker.add_issue(
                "installing",
                "Rolled-back version label mismatch",
                (
                    "wheel filename version="
                    f"{expected_version} but import reports version="
                    f"{rolled_back_version}; "
                    "possible wheel naming issue or pip normalisation difference"
                ),
            )
            self._tracker.log(
                "WARNING: rolled-back version mismatch "
                f"(wheel={expected_version}, import={rolled_back_version})",
            )
        self._tracker.log(f"Rolled back to {wheel.name} (verified version={rolled_back_version})")
        return True

    async def _verify_installed_version(self, *, phase: str) -> str | None:
        venv_python = reinstall_python_executable(self._config.repo)
        rc, stdout, stderr = await self._commands.run(
            [venv_python, "-c", "from vibesensor import __version__; print(__version__)"],
            phase=phase,
            timeout=30,
            sudo=False,
        )
        if rc == 0:
            return stdout.strip()
        message = (
            f"Post-install verification failed (exit {rc})"
            if phase == "installing"
            else f"Post-rollback verification failed (exit {rc})"
        )
        if phase == "installing":
            self._tracker.fail(phase, message, stderr)
        else:
            self._tracker.add_issue(phase, message, stderr)
        return None
