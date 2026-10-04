"""Firmware build version: ``<release version>+<commit>``, stamped at build time.

PlatformIO runs this file as an extra script for every firmware env
(``firmware/esp/platformio.ini``); it defines ``VIBESENSOR_FIRMWARE_VERSION``
for the firmware sources, which send it in every HELLO.

The release version and commit come from ``apps/server/vibesensor/_version.py``,
which the release workflow stamps before it builds the firmware, so a release
build reports the server release it ships with (``2026.10.4.1+0123456789ab``).
A local build reports ``0.0.0-dev+<checkout commit>``. The server compares the
reported version with the firmware bundled on the Pi
(``vibesensor.domain.sensor_firmware``).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# HELLO carries at most this many firmware-version bytes (HELLO_MAX_NAME_BYTES).
MAX_VERSION_BYTES = 32
COMMIT_CHARS = 12
_VERSION_FILE = Path("apps") / "server" / "vibesensor" / "_version.py"
_VERSION_RE = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
_COMMIT_RE = re.compile(r'^__commit__ = "([0-9a-f]*)"$', re.MULTILINE)


def _checkout_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def firmware_build_version(repo_root: Path) -> str:
    """Return the version string a firmware built from *repo_root* reports."""
    text = (repo_root / _VERSION_FILE).read_text(encoding="utf-8")
    version_match = _VERSION_RE.search(text)
    commit_match = _COMMIT_RE.search(text)
    version = version_match.group(1) if version_match else "0.0.0-dev"
    commit = commit_match.group(1) if commit_match else ""
    commit = commit or _checkout_commit(repo_root)
    build_version = f"{version}+{commit[:COMMIT_CHARS]}" if commit else version
    if len(build_version.encode("utf-8")) > MAX_VERSION_BYTES:
        raise SystemExit(
            f"Firmware version {build_version!r} exceeds the {MAX_VERSION_BYTES}-byte HELLO field."
        )
    return build_version


def _stamp_platformio_build() -> None:
    """Define the version for the firmware sources (PlatformIO post script)."""
    scons = globals()
    scons["Import"]("projenv")
    projenv = scons["projenv"]
    repo_root = Path(projenv.subst("$PROJECT_DIR")).resolve().parents[1]
    build_version = firmware_build_version(repo_root)
    print(f"VibeSensor firmware version: {build_version}")
    define = ("VIBESENSOR_FIRMWARE_VERSION", projenv.StringifyMacro(build_version))
    projenv.Append(CPPDEFINES=[define])


# SCons exposes Import() to the scripts PlatformIO runs; a plain import does not.
if "Import" in globals():
    _stamp_platformio_build()
