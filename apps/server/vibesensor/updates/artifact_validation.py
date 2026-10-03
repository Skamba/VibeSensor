"""Wheel artifact validation helpers for updater workflows."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from email.message import Message
from email.parser import Parser
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

__all__ = [
    "WheelMetadata",
    "read_wheel_metadata",
    "sha256_file",
    "versions_match",
    "wheel_artifact_problem",
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


def versions_match(actual_version: str, expected_version: str) -> bool:
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
    elif expected_version and not versions_match(metadata.version, expected_version):
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


def wheel_artifact_problem(wheel_path: Path) -> tuple[str, str] | None:
    """Return ``(message, detail)`` when *wheel_path* is not a usable server wheel."""
    if not wheel_path.is_file():
        return "Downloaded wheel is missing", str(wheel_path)
    if wheel_path.suffix != ".whl":
        return "Downloaded wheel is not a wheel", str(wheel_path)
    if not zipfile.is_zipfile(wheel_path):
        return "Downloaded wheel is corrupt", f"{wheel_path} is not a valid wheel archive"
    try:
        with zipfile.ZipFile(wheel_path) as wheel_zip:
            bad_member = wheel_zip.testzip()
            if bad_member is not None:
                return (
                    "Downloaded wheel is corrupt",
                    f"{wheel_path} failed archive CRC validation at {bad_member}",
                )
            if not any(name.endswith(".dist-info/METADATA") for name in wheel_zip.namelist()):
                return "Downloaded wheel is incomplete", f"{wheel_path} has no dist-info metadata"
    except (OSError, zipfile.BadZipFile) as exc:
        return "Downloaded wheel could not be opened", f"{wheel_path}: {exc}"
    metadata_errors = wheel_metadata_validation_errors(wheel_path, expected_name="vibesensor")
    if metadata_errors:
        return "Downloaded wheel metadata is invalid", "; ".join(metadata_errors)
    return None


def sha256_file(path: Path) -> str:
    """Hash a file as lowercase SHA-256 without loading it fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
