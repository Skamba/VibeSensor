"""Local install, rollback, and firmware-refresh operations for updater runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .runner import UpdateCommandExecutor
from .status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class RollbackSnapshotMetadata:
    version: str
    wheel_name: str
    sha256: str


_ROLLBACK_METADATA_FILE = "rollback_snapshot.json"


@dataclass(frozen=True, slots=True)
class UpdateInstallerConfig:
    repo: Path
    rollback_dir: Path
    reinstall_timeout_s: float
    firmware_refresh_timeout_s: float


class UpdateInstaller:
    """Owns install, rollback snapshotting, rollback, and firmware cache refresh."""

    __slots__ = ("_commands", "_config", "_tracker")

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

    def _rollback_metadata_path(self) -> Path:
        return self._config.rollback_dir / _ROLLBACK_METADATA_FILE

    def _write_rollback_metadata(self, metadata: RollbackSnapshotMetadata) -> None:
        self._config.rollback_dir.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                {
                    "version": metadata.version,
                    "wheel_name": metadata.wheel_name,
                    "sha256": metadata.sha256,
                },
                indent=2,
            )
            + "\n"
        )
        fd, temp_path_text = tempfile.mkstemp(
            prefix=".rollback_snapshot.",
            suffix=".tmp",
            dir=self._config.rollback_dir,
            text=True,
        )
        temp_path = Path(temp_path_text)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._rollback_metadata_path())
        finally:
            temp_path.unlink(missing_ok=True)

    def _rollback_wheels(self) -> list[Path]:
        return sorted(
            self._config.rollback_dir.glob("vibesensor-*.whl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _prune_rollback_wheels(self, *, keep_name: str) -> None:
        for old_wheel in self._rollback_wheels():
            if old_wheel.name != keep_name:
                old_wheel.unlink(missing_ok=True)

    def _load_rollback_metadata(self) -> RollbackSnapshotMetadata | None:
        metadata_path = self._rollback_metadata_path()
        if not metadata_path.is_file():
            return None
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self._tracker.add_issue(
                "installing",
                "Rollback metadata is unreadable",
                f"{metadata_path}: {exc}",
            )
            return None
        version = str(raw.get("version") or "")
        wheel_name = str(raw.get("wheel_name") or "")
        sha256 = str(raw.get("sha256") or "")
        if not version or not wheel_name or not sha256:
            self._tracker.add_issue(
                "installing",
                "Rollback metadata is incomplete",
                f"{metadata_path} is missing version, wheel_name, or sha256",
            )
            return None
        return RollbackSnapshotMetadata(version=version, wheel_name=wheel_name, sha256=sha256)

    def _report_artifact_validation_failure(
        self,
        *,
        phase: str,
        message: str,
        detail: str,
        fatal: bool,
    ) -> None:
        if fatal:
            self._tracker.fail(phase, message, detail)
        else:
            self._tracker.add_issue(phase, message, detail)

    def _validate_wheel_file(
        self,
        wheel_path: Path,
        *,
        phase: str,
        context: str,
        fatal: bool,
        expected_sha256: str | None = None,
    ) -> bool:
        if not wheel_path.is_file():
            self._report_artifact_validation_failure(
                phase=phase,
                message=f"{context} is missing",
                detail=str(wheel_path),
                fatal=fatal,
            )
            return False
        if wheel_path.suffix != ".whl":
            self._report_artifact_validation_failure(
                phase=phase,
                message=f"{context} is not a wheel",
                detail=str(wheel_path),
                fatal=fatal,
            )
            return False
        if not zipfile.is_zipfile(wheel_path):
            self._report_artifact_validation_failure(
                phase=phase,
                message=f"{context} is corrupt",
                detail=f"{wheel_path} is not a valid wheel archive",
                fatal=fatal,
            )
            return False
        try:
            with zipfile.ZipFile(wheel_path) as wheel_zip:
                bad_member = wheel_zip.testzip()
                if bad_member is not None:
                    self._report_artifact_validation_failure(
                        phase=phase,
                        message=f"{context} is corrupt",
                        detail=f"{wheel_path} failed archive CRC validation at {bad_member}",
                        fatal=fatal,
                    )
                    return False
                if not any(name.endswith(".dist-info/METADATA") for name in wheel_zip.namelist()):
                    self._report_artifact_validation_failure(
                        phase=phase,
                        message=f"{context} is incomplete",
                        detail=f"{wheel_path} is missing dist-info metadata",
                        fatal=fatal,
                    )
                    return False
        except (OSError, zipfile.BadZipFile) as exc:
            self._report_artifact_validation_failure(
                phase=phase,
                message=f"{context} could not be opened",
                detail=f"{wheel_path}: {exc}",
                fatal=fatal,
            )
            return False
        if expected_sha256:
            actual_sha256 = _sha256_file(wheel_path)
            if actual_sha256 != expected_sha256.lower():
                self._report_artifact_validation_failure(
                    phase=phase,
                    message=f"{context} checksum mismatch",
                    detail=(
                        f"expected={expected_sha256.lower()} actual={actual_sha256} "
                        f"path={wheel_path}"
                    ),
                    fatal=fatal,
                )
                return False
        return True

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> None:
        self._tracker.log("Refreshing ESP firmware cache...")
        venv_python = self.reinstall_python_executable(self._config.repo)
        refresh_exe = str(Path(venv_python).with_name("vibesensor-fw-refresh"))
        refresh_args = ["--cache-dir", "/var/lib/vibesensor/firmware"]
        if pinned_tag:
            refresh_args.extend(["--tag", pinned_tag])
        refresh_cmd = (
            [venv_python, "-m", "vibesensor.use_cases.updates.firmware_cache", *refresh_args]
            if not Path(refresh_exe).is_file()
            else [refresh_exe, *refresh_args]
        )
        rc, _, stderr = await self._commands.run(
            refresh_cmd,
            phase="downloading",
            timeout=self._config.firmware_refresh_timeout_s,
            sudo=False,
        )
        if rc != 0:
            self._tracker.add_issue(
                "downloading",
                f"ESP firmware cache refresh failed (exit {rc})",
                stderr,
            )
            self._tracker.log("ESP firmware refresh failed; continuing with existing cache")
            return
        self._tracker.log("ESP firmware cache refresh completed successfully")

    async def snapshot_for_rollback(self) -> bool:
        self._config.rollback_dir.mkdir(parents=True, exist_ok=True)
        venv_python = self.reinstall_python_executable(self._config.repo)
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
            if not self._validate_wheel_file(
                rollback_wheel,
                phase="installing",
                context="Rollback snapshot wheel",
                fatal=False,
            ):
                return False
            rollback_sha256 = _sha256_file(rollback_wheel)
            promoted_wheel = self._config.rollback_dir / rollback_wheel.name
            rollback_wheel.replace(promoted_wheel)
            try:
                self._write_rollback_metadata(
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
            self._prune_rollback_wheels(keep_name=promoted_wheel.name)
            self._tracker.log(
                "Rollback snapshot created successfully "
                f"(wheel={promoted_wheel.name}, sha256={rollback_sha256})",
            )
            return True

    async def install_release(self, wheel_path: Path, expected_version: str) -> bool:
        if not self._validate_wheel_file(
            wheel_path,
            phase="installing",
            context="Downloaded wheel",
            fatal=True,
        ):
            return False
        venv_python = self.reinstall_python_executable(self._config.repo)
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
        metadata = self._load_rollback_metadata()
        rollback_wheels = self._rollback_wheels()
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

        if not self._validate_wheel_file(
            wheel,
            phase="installing",
            context="Rollback wheel",
            fatal=False,
            expected_sha256=expected_sha256,
        ):
            return False

        venv_python = self.reinstall_python_executable(self._config.repo)
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
        venv_python = self.reinstall_python_executable(self._config.repo)
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

    @staticmethod
    def reinstall_venv_python_path(repo: Path) -> Path:
        return repo / "apps" / "server" / ".venv" / "bin" / "python3"

    @staticmethod
    def reinstall_venv_config_path(repo: Path) -> Path:
        return repo / "apps" / "server" / ".venv" / "pyvenv.cfg"

    @classmethod
    def is_reinstall_venv_ready(cls, repo: Path) -> bool:
        venv_python = cls.reinstall_venv_python_path(repo)
        if not (venv_python.is_file() and os.access(venv_python, os.X_OK)):
            return False
        return cls.reinstall_venv_config_path(repo).is_file()

    @classmethod
    def reinstall_python_executable(cls, repo: Path) -> str:
        return str(cls.reinstall_venv_python_path(repo))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
