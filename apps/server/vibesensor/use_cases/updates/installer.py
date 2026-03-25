"""Local install and rollback orchestration for updater runs."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from vibesensor.use_cases.updates.artifact_validation import (
    WheelArtifactValidator,
    read_wheel_metadata,
    sha256_file,
    wheel_dependency_issues,
    wheel_metadata_validation_errors,
)
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


_TARGET_ENV_SNAPSHOT_SCRIPT = "\n".join(
    [
        "import importlib.metadata as metadata",
        "import json",
        "import sys",
        "from packaging.markers import default_environment",
        "from packaging.utils import canonicalize_name",
        "payload = json.loads(sys.argv[1])",
        "distribution_names = [",
        "    canonicalize_name(str(name))",
        "    for name in payload.get('distribution_names', [])",
        "]",
        "installed_versions = {}",
        "for distribution_name in distribution_names:",
        "    try:",
        "        installed_versions[distribution_name] = metadata.version(distribution_name)",
        "    except metadata.PackageNotFoundError:",
        "        installed_versions[distribution_name] = ''",
        "marker_environment = default_environment()",
        "print(json.dumps({",
        "    'python_full_version': marker_environment.get('python_full_version', ''),",
        "    'marker_environment': marker_environment,",
        "    'installed_versions': installed_versions,",
        "}))",
    ],
)


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

    def _existing_local_rollback_wheel(self, *, current_version: str) -> Path | None:
        candidates = sorted(
            self._config.rollback_dir.glob(f"vibesensor-{current_version}-*.whl"),
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
                "Ignoring existing rollback wheel "
                f"{candidate.name}: {'; '.join(errors)}",
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
        package_dir = self._config.repo / "apps" / "server"
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
                "Package-index rollback download failed "
                f"(exit {rc}): {stderr}",
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
        rollback_sha256 = sha256_file(rollback_wheel)
        promoted_wheel = self._config.rollback_dir / rollback_wheel.name
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
        self._config.rollback_dir.mkdir(parents=True, exist_ok=True)
        venv_python = reinstall_python_executable(self._config.repo)
        from vibesensor import __version__ as current_version

        self._tracker.log(f"Creating rollback snapshot (version={current_version})")
        if existing_wheel := self._existing_local_rollback_wheel(current_version=current_version):
            return self._write_rollback_snapshot(
                rollback_wheel=existing_wheel,
                current_version=current_version,
            )
        with tempfile.TemporaryDirectory(
            prefix="vibesensor-rollback-stage-",
            dir=self._config.rollback_dir.parent,
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
                (self._config.rollback_dir / "rollback_version.txt").write_text(
                    current_version,
                    encoding="utf-8",
                )
                return False
            return self._write_rollback_snapshot(
                rollback_wheel=rollback_wheel,
                current_version=current_version,
            )

    async def install_release(self, wheel_path: Path, expected_version: str) -> bool:
        if not self._wheel_validator.validate_wheel(
            wheel_path,
            phase="installing",
            context="Downloaded wheel",
            fatal=True,
        ):
            return False
        venv_python = reinstall_python_executable(self._config.repo)
        if not await self._validate_dependency_compatibility(wheel_path, venv_python=venv_python):
            return False
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

    async def _validate_dependency_compatibility(
        self,
        wheel_path: Path,
        *,
        venv_python: str,
    ) -> bool:
        metadata = read_wheel_metadata(wheel_path)
        requirement_names = sorted(
            {
                canonicalize_name(Requirement(raw_requirement).name)
                for raw_requirement in metadata.requires_dist
            },
        )
        if not metadata.requires_python and not requirement_names:
            return True

        rc, stdout, stderr = await self._commands.run(
            [
                venv_python,
                "-c",
                _TARGET_ENV_SNAPSHOT_SCRIPT,
                json.dumps({"distribution_names": requirement_names}),
            ],
            phase="installing",
            timeout=30,
            sudo=False,
        )
        if rc != 0:
            self._tracker.fail(
                "installing",
                f"Could not validate wheel dependency compatibility (exit {rc})",
                stderr or stdout,
            )
            return False
        try:
            snapshot = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            self._tracker.fail(
                "installing",
                "Could not parse wheel dependency compatibility results",
                stdout or stderr,
            )
            return False

        marker_environment_raw = snapshot.get("marker_environment", {})
        installed_versions_raw = snapshot.get("installed_versions", {})
        if not isinstance(marker_environment_raw, dict) or not isinstance(
            installed_versions_raw,
            dict,
        ):
            self._tracker.fail(
                "installing",
                "Could not parse wheel dependency compatibility results",
                stdout or stderr,
            )
            return False
        issues = wheel_dependency_issues(
            metadata,
            python_full_version=str(snapshot.get("python_full_version") or ""),
            marker_environment={
                str(key): str(value)
                for key, value in marker_environment_raw.items()
                if isinstance(key, str)
            },
            installed_versions={
                str(key): str(value)
                for key, value in installed_versions_raw.items()
                if isinstance(key, str)
            },
        )
        if issues:
            self._tracker.fail(
                "installing",
                "Downloaded wheel is incompatible with the current environment",
                "; ".join(issues),
            )
            return False
        self._tracker.log("Validated wheel dependency compatibility against target environment")
        return True

    async def rollback(self) -> bool:
        self._tracker.log("Rolling back to previous version...")
        metadata = self._rollback_snapshots.load_metadata()
        rollback_wheels = self._rollback_snapshots.rollback_wheels()
        if not rollback_wheels:
            self._tracker.add_issue("installing", "No rollback wheel available")
            return False

        wheel: Path | None = None
        expected_version = ""
        candidates: list[tuple[Path, str, str | None]] = []
        if metadata is not None:
            primary_wheel = self._config.rollback_dir / metadata.wheel_name
            candidates.append((primary_wheel, metadata.version, metadata.sha256))
            for fallback_wheel in rollback_wheels:
                if fallback_wheel.name == metadata.wheel_name:
                    continue
                wheel_parts = fallback_wheel.stem.split("-")
                fallback_version = wheel_parts[1] if len(wheel_parts) >= 2 else ""
                candidates.append((fallback_wheel, fallback_version, None))
        else:
            self._tracker.log(
                "Rollback metadata missing; falling back to newest "
                "rollback wheel without checksum pin",
            )
            for fallback_wheel in rollback_wheels:
                wheel_parts = fallback_wheel.stem.split("-")
                fallback_version = wheel_parts[1] if len(wheel_parts) >= 2 else ""
                candidates.append((fallback_wheel, fallback_version, None))

        for idx, (candidate_wheel, candidate_version, candidate_sha256) in enumerate(candidates):
            if not candidate_wheel.is_file():
                if idx == 0 and metadata is not None:
                    self._tracker.add_issue(
                        "installing",
                        "Rollback snapshot wheel is missing",
                        f"metadata expected {candidate_wheel}",
                    )
                continue
            context = "Rollback wheel" if idx == 0 else "Fallback rollback wheel"
            if not self._wheel_validator.validate_wheel(
                candidate_wheel,
                phase="installing",
                context=context,
                fatal=False,
                expected_sha256=candidate_sha256,
            ):
                if idx == 0 and len(candidates) > 1:
                    self._tracker.log(
                        "Primary rollback snapshot could not be used; trying older rollback wheel"
                    )
                continue
            if idx > 0:
                self._tracker.log(f"Using fallback rollback wheel {candidate_wheel.name}")
            wheel = candidate_wheel
            expected_version = candidate_version
            break
        if wheel is None:
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
