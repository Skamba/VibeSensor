"""Firmware build identity ``fw-<date>+<digest>``, stamped at build time.

PlatformIO runs this file as an extra script for every firmware env
(``firmware/esp/platformio.ini``); it defines ``VIBESENSOR_FIRMWARE_VERSION``
for the firmware sources, which send it in every HELLO.

The identity changes only when the firmware build inputs change: ``platformio.ini``
(platform, libraries, flags) and everything under ``src/``, ``lib/`` and
``include/`` in ``firmware/esp`` (:data:`FIRMWARE_INPUTS`).

- ``<digest>``: 12 hex characters of a SHA-256 over those files, so equal digests
  mean the same firmware.
- ``<date>``: the UTC committer date (``YYYYMMDD.HHMM``) of the newest commit that
  touched those files, so a later identity is newer firmware. ``00000000.0000``
  when git cannot tell.

The server release and commit do not feed in: a release that leaves the firmware
alone ships the identity its sensors already report. An uncommitted change keeps
the date and changes the digest. The release tooling reads the identity back out
of each ``firmware.bin`` into ``flash.json``, and the server compares it with each
sensor's HELLO (``vibesensor.domain.sensor_firmware``).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

FIRMWARE_DIR = Path("firmware") / "esp"
FIRMWARE_INPUTS = ("platformio.ini", "include", "lib", "src")
DIGEST_CHARS = 12
UNKNOWN_DATE = "00000000.0000"


def _input_files(firmware_dir: Path) -> list[Path]:
    files: list[Path] = []
    for name in FIRMWARE_INPUTS:
        path = firmware_dir / name
        if path.is_dir():
            files.extend(child for child in path.rglob("*") if child.is_file())
        elif path.is_file():
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(firmware_dir).as_posix())


def firmware_inputs_digest(firmware_dir: Path) -> str:
    """Digest of the firmware build inputs: a ``sha256sum``-style manifest, hashed."""
    manifest = hashlib.sha256()
    for path in _input_files(firmware_dir):
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.update(
            f"{content}  {path.relative_to(firmware_dir).as_posix()}\n".encode()
        )
    return manifest.hexdigest()[:DIGEST_CHARS]


def _last_input_commit_date(repo_root: Path) -> str:
    paths = [(FIRMWARE_DIR / name).as_posix() for name in FIRMWARE_INPUTS]
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%cd",
                "--date=format-local:%Y%m%d.%H%M",
                "--",
                *paths,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "TZ": "UTC"},
        )
    except (OSError, subprocess.CalledProcessError):
        return UNKNOWN_DATE
    return result.stdout.strip() or UNKNOWN_DATE


def firmware_build_version(repo_root: Path) -> str:
    """Return the identity a firmware built from *repo_root* reports (29 bytes)."""
    digest = firmware_inputs_digest(repo_root / FIRMWARE_DIR)
    return f"fw-{_last_input_commit_date(repo_root)}+{digest}"


def _stamp_platformio_build() -> None:
    """Define the identity for the firmware sources (PlatformIO post script)."""
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
