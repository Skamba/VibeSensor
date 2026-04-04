"""Wheel artifact validation helpers for updater workflows."""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from email.parser import Parser
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder

__all__ = [
    "WheelArtifactValidator",
    "WheelMetadata",
    "read_wheel_metadata",
    "sha256_file",
    "wheel_dependency_issues",
    "wheel_metadata_validation_errors",
]


@dataclass(frozen=True, slots=True)
class WheelMetadata:
    """Parsed wheel metadata relevant to release/update validation."""

    name: str
    version: str
    requires_python: str = ""
    requires_dist: tuple[str, ...] = ()


def _metadata_message_from_archive(wheel_zip: zipfile.ZipFile) -> Message:
    """Return the parsed ``METADATA`` message stored inside a wheel archive."""
    metadata_name = next(
        (name for name in wheel_zip.namelist() if name.endswith(".dist-info/METADATA")),
        "",
    )
    if not metadata_name:
        raise ValueError("wheel archive is missing dist-info metadata")
    try:
        metadata_text = wheel_zip.read(metadata_name).decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise ValueError(f"could not read wheel metadata: {exc}") from exc
    return Parser().parsestr(metadata_text)


def _parse_metadata_message(message: Message) -> WheelMetadata:
    """Project the raw metadata message into the small updater-facing model."""
    return WheelMetadata(
        name=(message.get("Name") or "").strip(),
        version=(message.get("Version") or "").strip(),
        requires_python=(message.get("Requires-Python") or "").strip(),
        requires_dist=tuple(
            entry.strip()
            for entry in message.get_all("Requires-Dist", [])
            if isinstance(entry, str) and entry.strip()
        ),
    )


def read_wheel_metadata(wheel_path: Path) -> WheelMetadata:
    """Read and parse ``.dist-info/METADATA`` from a wheel archive."""
    with zipfile.ZipFile(wheel_path) as wheel_zip:
        return _parse_metadata_message(_metadata_message_from_archive(wheel_zip))


def _versions_match(actual_version: str, expected_version: str) -> bool:
    """Compare versions with PEP 440 normalization when possible."""

    try:
        return Version(actual_version) == Version(expected_version)
    except InvalidVersion:
        return actual_version == expected_version


def wheel_metadata_validation_errors(
    wheel_path: Path,
    *,
    expected_name: str | None = None,
    expected_version: str | None = None,
) -> list[str]:
    """Return human-readable wheel metadata problems for validation/reporting."""
    try:
        metadata = read_wheel_metadata(wheel_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return [f"{wheel_path}: {exc}"]

    errors: list[str] = []
    if not metadata.name:
        errors.append("wheel metadata is missing Name")
    elif expected_name and metadata.name != expected_name:
        errors.append(
            f"wheel metadata Name {metadata.name!r} does not match expected {expected_name!r}",
        )
    if not metadata.version:
        errors.append("wheel metadata is missing Version")
    elif expected_version and not _versions_match(metadata.version, expected_version):
        errors.append(
            "wheel metadata Version "
            f"{metadata.version!r} does not match expected {expected_version!r}",
        )
    if metadata.requires_python:
        try:
            SpecifierSet(metadata.requires_python)
        except InvalidSpecifier as exc:
            errors.append(
                f"wheel metadata Requires-Python {metadata.requires_python!r} is invalid: {exc}",
            )
    for raw_requirement in metadata.requires_dist:
        try:
            Requirement(raw_requirement)
        except InvalidRequirement as exc:
            errors.append(
                f"wheel metadata Requires-Dist {raw_requirement!r} is invalid: {exc}",
            )
    return errors


def wheel_dependency_issues(
    metadata: WheelMetadata,
    *,
    python_full_version: str,
    marker_environment: Mapping[str, str],
    installed_versions: Mapping[str, str],
) -> list[str]:
    """Evaluate wheel dependency metadata against a concrete target environment."""
    issues: list[str] = []
    environment = {key: str(value) for key, value in marker_environment.items()}
    if metadata.requires_python:
        try:
            specifier = SpecifierSet(metadata.requires_python)
        except InvalidSpecifier as exc:
            return [
                f"wheel metadata Requires-Python {metadata.requires_python!r} is invalid: {exc}",
            ]
        if python_full_version and not specifier.contains(python_full_version, prereleases=True):
            issues.append(
                "Python "
                f"{python_full_version} does not satisfy wheel Requires-Python "
                f"{metadata.requires_python}",
            )
    for raw_requirement in metadata.requires_dist:
        try:
            requirement = Requirement(raw_requirement)
        except InvalidRequirement as exc:
            issues.append(
                f"wheel metadata Requires-Dist {raw_requirement!r} is invalid: {exc}",
            )
            continue
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue
        requirement_name = canonicalize_name(requirement.name)
        installed_version = installed_versions.get(requirement_name, "")
        if not installed_version:
            suffix = str(requirement.specifier) if requirement.specifier else ""
            issues.append(f"Missing dependency: {requirement.name}{suffix}")
            continue
        if requirement.specifier and not requirement.specifier.contains(
            installed_version,
            prereleases=True,
        ):
            issues.append(
                f"Dependency {requirement.name}=={installed_version} does not satisfy "
                f"{requirement.specifier}",
            )
    return issues


class WheelArtifactValidator:
    """Validate updater wheel artifacts through explicit status services."""

    __slots__ = ("_status_controller", "_status_recorder")

    def __init__(
        self,
        *,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder

    def _report_failure(
        self,
        *,
        phase: str,
        message: str,
        detail: str,
        fatal: bool,
    ) -> None:
        if fatal:
            self._status_recorder.add_issue(phase, message, detail)
            self._status_controller.mark_failed()
        else:
            self._status_recorder.add_issue(phase, message, detail)

    def validate_wheel(
        self,
        wheel_path: Path,
        *,
        phase: str,
        context: str,
        fatal: bool,
        expected_sha256: str | None = None,
    ) -> bool:
        """Validate a wheel file and report any failure through the tracker."""
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
        metadata_errors = wheel_metadata_validation_errors(
            wheel_path,
            expected_name="vibesensor",
        )
        if metadata_errors:
            self._report_failure(
                phase=phase,
                message=f"{context} metadata is invalid",
                detail="; ".join(metadata_errors),
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
    """Hash a file as lowercase SHA-256 without loading it fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
