"""Wheel artifact validation helpers for updater workflows."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from vibesensor.use_cases.updates.status import UpdateStatusTracker

__all__ = ["WheelArtifactValidator", "sha256_file"]


class WheelArtifactValidator:
    """Validate updater wheel artifacts and report failures through the status tracker."""

    __slots__ = ("_tracker",)

    def __init__(self, tracker: UpdateStatusTracker) -> None:
        self._tracker = tracker

    def _report_failure(
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

    def validate_wheel(
        self,
        wheel_path: Path,
        *,
        phase: str,
        context: str,
        fatal: bool,
        expected_sha256: str | None = None,
    ) -> bool:
        if not wheel_path.is_file():
            self._report_failure(
                phase=phase,
                message=f"{context} is missing",
                detail=str(wheel_path),
                fatal=fatal,
            )
            return False
        if wheel_path.suffix != ".whl":
            self._report_failure(
                phase=phase,
                message=f"{context} is not a wheel",
                detail=str(wheel_path),
                fatal=fatal,
            )
            return False
        if not zipfile.is_zipfile(wheel_path):
            self._report_failure(
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
                    self._report_failure(
                        phase=phase,
                        message=f"{context} is corrupt",
                        detail=f"{wheel_path} failed archive CRC validation at {bad_member}",
                        fatal=fatal,
                    )
                    return False
                if not any(name.endswith(".dist-info/METADATA") for name in wheel_zip.namelist()):
                    self._report_failure(
                        phase=phase,
                        message=f"{context} is incomplete",
                        detail=f"{wheel_path} is missing dist-info metadata",
                        fatal=fatal,
                    )
                    return False
        except (OSError, zipfile.BadZipFile) as exc:
            self._report_failure(
                phase=phase,
                message=f"{context} could not be opened",
                detail=f"{wheel_path}: {exc}",
                fatal=fatal,
            )
            return False
        if expected_sha256:
            actual_sha256 = sha256_file(wheel_path)
            if actual_sha256 != expected_sha256.lower():
                self._report_failure(
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
