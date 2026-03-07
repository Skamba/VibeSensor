"""Local install, rollback, and firmware-refresh operations for updater runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .commands import UpdateCommandExecutor
from .status import UpdateStatusTracker


@dataclass(frozen=True, slots=True)
class UpdateInstallerConfig:
    repo: Path
    rollback_dir: Path
    reinstall_timeout_s: float
    firmware_refresh_timeout_s: float


class UpdateInstaller:
    """Owns install, rollback snapshotting, rollback, and firmware cache refresh."""

    __slots__ = ("_commands", "_tracker", "_config")

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

    async def refresh_esp_firmware(self, pinned_tag: str = "") -> None:
        self._tracker.log("Refreshing ESP firmware cache...")
        venv_python = self.reinstall_python_executable(self._config.repo)
        refresh_exe = str(Path(venv_python).with_name("vibesensor-fw-refresh"))
        refresh_args = ["--cache-dir", "/var/lib/vibesensor/firmware"]
        if pinned_tag:
            refresh_args.extend(["--tag", pinned_tag])
        refresh_cmd = (
            [venv_python, "-m", "vibesensor.firmware_cache", *refresh_args]
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
        rc, _, stderr = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--no-build-isolation",
                "-d",
                str(self._config.rollback_dir),
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
        for old_wheel in self._config.rollback_dir.glob("vibesensor-*.whl"):
            wheel_parts = old_wheel.stem.split("-")
            wheel_version = wheel_parts[1] if len(wheel_parts) >= 2 else ""
            if wheel_version != current_version:
                old_wheel.unlink(missing_ok=True)
        self._tracker.log("Rollback snapshot created successfully")
        return True

    async def install_release(self, wheel_path: Path, expected_version: str) -> bool:
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
        rollback_wheels = sorted(
            self._config.rollback_dir.glob("vibesensor-*.whl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not rollback_wheels:
            self._tracker.add_issue("installing", "No rollback wheel available")
            return False

        venv_python = self.reinstall_python_executable(self._config.repo)
        wheel = rollback_wheels[0]
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

        wheel_parts = wheel.stem.split("-")
        expected_version = wheel_parts[1] if len(wheel_parts) >= 2 else ""
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
                f"(wheel={expected_version}, import={rolled_back_version})"
            )
        self._tracker.log(
            f"Rolled back to {wheel.name} (verified version={rolled_back_version})"
        )
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