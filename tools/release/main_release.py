#!/usr/bin/env python3
"""Helpers for the main-release workflow's extracted release steps."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request

_STANDARD_ESP32_APP_OFFSET = "0x10000"
_PARTITION_ENTRY_SIZE = 32
_PARTITION_MAGIC = b"\xaa\x50"
_PARTITION_TYPE_APP = 0x00
_PARTITION_SUBTYPE_FACTORY = 0x00
_PARTITION_SUBTYPE_OTA_0 = 0x10
_ESP_IMAGE_MAGIC = 0xE9
# esptool chip names by the chip ID in an app image's extended header
# (esptool's IMAGE_CHIP_ID per target).
_CHIP_BY_IMAGE_ID = {
    0: "esp32",
    2: "esp32s2",
    5: "esp32c3",
    9: "esp32s3",
    12: "esp32c2",
    13: "esp32c6",
    16: "esp32h2",
    18: "esp32p4",
    20: "esp32c61",
    23: "esp32c5",
}
# The firmware embeds its build version after this marker (kFirmwareVersionTag in
# firmware/esp/src/runtime_config.h), so the image itself says what it reports.
_FIRMWARE_VERSION_MARKER = b"VIBESENSOR_FIRMWARE_VERSION="
_GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_TIMEOUT_S = 30

# The Pi images run Raspberry Pi OS Lite Trixie (infra/pi-image/pi-gen): CPython
# 3.13 and glibc 2.41 on either the 32-bit armhf userland (armv7l, the published
# image) or the 64-bit arm64 one (aarch64). Each release ships one dependency
# wheelhouse per userland; the updater picks the one its interpreter needs
# (vibesensor.updates.releases.release_discovery.device_wheelhouse_platform).
PI_PYTHON_VERSION = "3.13"
_MANYLINUX_GLIBC_MINORS = (17, 24, 26, 27, 28, 31, 34, 35, 36, 38, 39)


@dataclass(frozen=True)
class PiWheelTarget:
    machine: str
    asset_prefix: str
    indexes: tuple[str, ...]
    # Dependencies published only as a pure-Python sdist: built into a
    # py3-none-any wheel on the CI host (pure Python, nothing compiles).
    pure_sdist_dependencies: tuple[str, ...] = ()

    @property
    def platforms(self) -> tuple[str, ...]:
        return (
            f"linux_{self.machine}",
            f"manylinux2014_{self.machine}",
            *(
                f"manylinux_2_{minor}_{self.machine}"
                for minor in _MANYLINUX_GLIBC_MINORS
            ),
        )


PI_WHEEL_TARGETS = {
    # PyPI has few armv7l wheels, so piwheels (Raspberry Pi OS's own wheel
    # index) fills in numpy, scipy, pyfftw, esptool, etc.
    "armv7l": PiWheelTarget(
        machine="armv7l",
        asset_prefix="vibesensor-wheelhouse",
        indexes=("https://pypi.org/simple", "https://www.piwheels.org/simple"),
    ),
    # PyPI has manylinux aarch64 wheels for every binary dependency; piwheels
    # is armhf-only, so esptool (sdist-only on PyPI) is built here. Updaters
    # before arm64 support take the first `vibesensor-wheelhouse-*.tar` asset,
    # so this name must not start with that prefix.
    "aarch64": PiWheelTarget(
        machine="aarch64",
        asset_prefix="vibesensor-arm64-wheelhouse",
        indexes=("https://pypi.org/simple",),
        pure_sdist_dependencies=("esptool",),
    ),
}


@dataclass(frozen=True)
class ReleaseVersionInfo:
    version: str
    tag: str
    bundle: str


@dataclass(frozen=True)
class ReleaseSummary:
    id: int
    tag: str
    title: str


def _run(
    command: list[str], *, cwd: Path | None = None, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=None if cwd is None else str(cwd),
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _repo_root(raw_path: str | None) -> Path:
    if raw_path is not None:
        return Path(raw_path).resolve()
    return Path(__file__).resolve().parents[2]


def _release_date(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    return f"{current.year}.{current.month}.{current.day}"


def _git_release_tags(repo_root: Path) -> list[str]:
    result = _run(
        ["git", "tag", "-l", "server-v*"],
        cwd=repo_root,
        capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def compute_release_version_info(
    repo_root: Path,
    *,
    now: datetime | None = None,
    existing_tags: list[str] | None = None,
) -> ReleaseVersionInfo:
    base_version = _release_date(now)
    prefix = f"server-v{base_version}"
    max_suffix: int | None = None
    for tag in (
        existing_tags if existing_tags is not None else _git_release_tags(repo_root)
    ):
        if not tag.startswith(prefix):
            continue
        suffix = tag[len(prefix) :]
        if suffix == "":
            candidate = 0
        elif re.fullmatch(r"\.\d+", suffix):
            candidate = int(suffix[1:])
        else:
            continue
        max_suffix = candidate if max_suffix is None else max(max_suffix, candidate)
    version = base_version if max_suffix is None else f"{base_version}.{max_suffix + 1}"
    return ReleaseVersionInfo(
        version=version,
        tag=f"server-v{version}",
        bundle=f"vibesensor-fw-v{version}.zip",
    )


def write_github_output(output_path: Path, version_info: ReleaseVersionInfo) -> None:
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(f"version={version_info.version}\n")
        handle.write(f"tag={version_info.tag}\n")
        handle.write(f"bundle={version_info.bundle}\n")


def stamp_version_file(version_file: Path, version: str, commit: str) -> None:
    version_file.write_text(
        "# Auto-generated by main-release workflow - do not edit.\n"
        f'__version__ = "{version}"\n'
        f'__commit__ = "{commit}"\n',
        encoding="utf-8",
    )


def build_server_wheel(repo_root: Path, version: str) -> Path:
    version_file = repo_root / "apps" / "server" / "vibesensor" / "_version.py"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    commit = _run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True
    ).stdout
    stamp_version_file(version_file, version, commit.strip())
    _run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "build"],
        cwd=repo_root,
    )
    _run([sys.executable, "-m", "build", "--wheel", "apps/server/"], cwd=repo_root)
    wheels = sorted((repo_root / "apps" / "server" / "dist").glob("*.whl"))
    if not wheels:
        raise SystemExit("No wheel produced under apps/server/dist.")
    return wheels[-1]


def _pi_target_args(target: PiWheelTarget) -> list[str]:
    args = [
        "--only-binary=:all:",
        "--python-version",
        PI_PYTHON_VERSION,
        "--implementation",
        "cp",
        "--abi",
        "cp" + PI_PYTHON_VERSION.replace(".", ""),
        "--abi",
        "abi3",
        "--abi",
        "none",
    ]
    for platform in target.platforms:
        args.extend(("--platform", platform))
    return args


def wheelhouse_name(version: str, machine: str) -> str:
    target = PI_WHEEL_TARGETS[machine]
    tag = "cp" + PI_PYTHON_VERSION.replace(".", "")
    return f"{target.asset_prefix}-{version}-{tag}-linux_{target.machine}.tar"


def _requires_dist(wheel_path: Path, name: str) -> str:
    """Return *wheel_path*'s requirement on *name* (``esptool<6,>=5.2.0``), marker dropped."""
    with zipfile.ZipFile(wheel_path) as wheel:
        metadata_name = next(
            entry for entry in wheel.namelist() if entry.endswith(".dist-info/METADATA")
        )
        metadata = wheel.read(metadata_name).decode("utf-8")
    for line in metadata.splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        requirement = line.removeprefix("Requires-Dist:").split(";", 1)[0].strip()
        project = re.split(r"[\s<>=!~\[(]", requirement, maxsplit=1)[0]
        if project.lower().replace("_", "-") == name:
            return requirement
    raise SystemExit(f"{wheel_path.name} does not require {name}.")


def _build_pure_sdist_wheels(
    target: PiWheelTarget, wheel_path: Path, wheel_dir: Path
) -> None:
    for name in target.pure_sdist_dependencies:
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
                "--index-url",
                target.indexes[0],
                _requires_dist(wheel_path, name),
            ]
        )
        built = sorted(wheel_dir.glob(f"{name.replace('-', '_')}-*.whl"))
        if not built or not all(w.name.endswith("-none-any.whl") for w in built):
            raise SystemExit(
                f"{name} did not build as a pure-Python wheel: "
                f"{[w.name for w in built]}"
            )


def build_wheelhouse(wheel_path: Path, output: Path, machine: str) -> Path:
    """Download every runtime dependency of *wheel_path* as Pi wheels into one tar.

    Binary wheels only, so the CI host never compiles anything (pure-Python
    sdist-only dependencies become py3-none-any wheels first), followed by an
    offline dry-run install that proves the set is complete for the target.
    """
    target = PI_WHEEL_TARGETS[machine]
    requirement = f"{wheel_path.resolve()}[esp]"
    index_args = ["--index-url", target.indexes[0]]
    for extra_index in target.indexes[1:]:
        index_args.extend(("--extra-index-url", extra_index))
    with tempfile.TemporaryDirectory(prefix="vibesensor-wheelhouse-") as tmp:
        wheel_dir = Path(tmp) / "wheels"
        wheel_dir.mkdir()
        _build_pure_sdist_wheels(target, wheel_path, wheel_dir)
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--dest",
                str(wheel_dir),
                "--find-links",
                str(wheel_dir),
                *_pi_target_args(target),
                *index_args,
                requirement,
            ]
        )
        # The server wheel ships as its own release asset.
        (wheel_dir / wheel_path.name).unlink(missing_ok=True)
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--ignore-installed",
                "--no-index",
                "--find-links",
                str(wheel_dir),
                *_pi_target_args(target),
                requirement,
            ]
        )
        wheels = sorted(wheel_dir.glob("*.whl"))
        if not wheels:
            raise SystemExit("pip download produced no dependency wheels.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w") as tar:
            for wheel in wheels:
                tar.add(wheel, arcname=wheel.name)
    return output


def _app_offset_from_partitions(env_dir: Path) -> str:
    """Return the offset of the app the bootloader starts on a fresh flash.

    Reads the built ``partitions.bin`` (32-byte ESP-IDF entries): the factory app
    when present, else ``ota_0``. pioarduino no longer exposes the offset in
    ``pio run -t envdump``, so the table itself is the source of truth.
    """
    table_path = env_dir / "partitions.bin"
    if not table_path.is_file():
        return _STANDARD_ESP32_APP_OFFSET
    table = table_path.read_bytes()
    app_offsets: dict[int, int] = {}
    for start in range(
        0, len(table) - _PARTITION_ENTRY_SIZE + 1, _PARTITION_ENTRY_SIZE
    ):
        entry = table[start : start + _PARTITION_ENTRY_SIZE]
        if entry[:2] != _PARTITION_MAGIC:
            break
        if entry[2] == _PARTITION_TYPE_APP:
            app_offsets.setdefault(entry[3], int.from_bytes(entry[4:8], "little"))
    for subtype in (_PARTITION_SUBTYPE_FACTORY, _PARTITION_SUBTYPE_OTA_0):
        if subtype in app_offsets:
            return hex(app_offsets[subtype])
    return _STANDARD_ESP32_APP_OFFSET


def _image_chip(firmware_bin: Path) -> str:
    """Return the esptool chip name a built app image targets.

    ESP32-family images carry their target in the extended header (the chip ID
    at bytes 12-13), so the binary itself says which chip it was built for.
    """
    header = firmware_bin.read_bytes()[:16]
    if len(header) < 16 or header[0] != _ESP_IMAGE_MAGIC:
        raise SystemExit(f"{firmware_bin} is not an ESP app image.")
    chip_id = int.from_bytes(header[12:14], "little")
    chip = _CHIP_BY_IMAGE_ID.get(chip_id)
    if chip is None:
        raise SystemExit(f"{firmware_bin} targets unknown ESP chip ID {chip_id}.")
    return chip


def _image_firmware_version(firmware_bin: Path) -> str:
    """Return the version a built app image reports in its HELLO."""
    image = firmware_bin.read_bytes()
    start = image.find(_FIRMWARE_VERSION_MARKER)
    end = image.find(b"\0", start)
    if start < 0 or end < 0:
        raise SystemExit(f"{firmware_bin} carries no firmware version stamp.")
    return image[start + len(_FIRMWARE_VERSION_MARKER) : end].decode("ascii")


def _platformio_flash_offsets(
    firmware_dir: Path, env_names: list[str]
) -> dict[str, dict[str, str]]:
    """Return ``{env: {image file name: offset}}`` from the PlatformIO build.

    These are the offsets ``pio run -t upload`` passes to esptool, so they follow
    the chip (the bootloader sits at 0x1000 on ESP32 but 0x0 on ESP32-C3).
    """
    result = _run(
        [
            "pio",
            "project",
            "metadata",
            "--project-dir",
            str(firmware_dir),
            *(arg for name in env_names for arg in ("--environment", name)),
            "--json-output",
        ],
        capture_output=True,
    )
    metadata = json.loads(result.stdout)
    return {
        name: {
            Path(image["path"]).name: image["offset"]
            for image in metadata[name]["extra"]["flash_images"]
        }
        for name in env_names
    }


def build_firmware_manifest(
    firmware_dir: Path,
    *,
    flash_offsets: dict[str, dict[str, str]],
    generated_from: str | None = None,
) -> dict[str, object]:
    """Describe each packaged env: its chip, its version and every image at its offset."""
    dist_dir = firmware_dir / "dist"
    environments: list[dict[str, object]] = []
    for env_dir in sorted(path for path in dist_dir.iterdir() if path.is_dir()):
        env_name = env_dir.name
        image_offsets = flash_offsets[env_name]
        segments: list[dict[str, str]] = []
        for artifact in sorted(env_dir.glob("*.bin")):
            if artifact.name == "firmware.bin":
                offset = _app_offset_from_partitions(env_dir)
            elif artifact.name in image_offsets:
                offset = image_offsets[artifact.name]
            else:
                raise SystemExit(
                    f"{env_name}/{artifact.name} has no flash offset in the "
                    "PlatformIO build metadata."
                )
            segments.append(
                {
                    "file": f"{env_name}/{artifact.name}",
                    "offset": offset,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            )
        segments.sort(key=lambda segment: int(segment["offset"], 16))
        environments.append(
            {
                "name": env_name,
                "chip": _image_chip(env_dir / "firmware.bin"),
                "firmware_version": _image_firmware_version(env_dir / "firmware.bin"),
                "segments": segments,
            }
        )
    return {
        "generated_from": generated_from or os.getenv("GITHUB_SHA", "unknown"),
        "environments": environments,
    }


def write_firmware_manifest(
    firmware_dir: Path,
    *,
    generated_from: str | None = None,
) -> Path:
    dist_dir = firmware_dir / "dist"
    if not dist_dir.is_dir():
        raise SystemExit(f"Firmware dist directory does not exist: {dist_dir}")
    env_names = sorted(path.name for path in dist_dir.iterdir() if path.is_dir())
    manifest = build_firmware_manifest(
        firmware_dir,
        flash_offsets=_platformio_flash_offsets(firmware_dir, env_names),
        generated_from=generated_from,
    )
    manifest_path = dist_dir / "flash.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def select_superseded_releases(
    releases: list[dict[str, object]],
    *,
    current_tag: str,
    release_title_prefix: str,
) -> list[ReleaseSummary]:
    title_prefix = f"{release_title_prefix} "
    selected: list[ReleaseSummary] = []
    for release in releases:
        release_id = release.get("id")
        if not isinstance(release_id, int):
            raise SystemExit("Release payload is missing an integer id.")
        tag = str(release.get("tag_name") or "")
        title = str(release.get("name") or "")
        if tag == current_tag or not tag.startswith("server-v"):
            continue
        if not title.startswith(title_prefix):
            continue
        selected.append(ReleaseSummary(id=release_id, tag=tag, title=title))
    return selected


def _github_token() -> str:
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN or GITHUB_TOKEN must be set.")
    return token


def _github_request(method: str, repo: str, path: str) -> object | None:
    api_path = f"/repos/{repo}/{path.lstrip('/')}"
    req = request.Request(
        f"{_GITHUB_API_BASE}{api_path}",
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {_github_token()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with request.urlopen(req, timeout=GITHUB_API_TIMEOUT_S) as response:
            payload = response.read().decode("utf-8")
    except error.HTTPError:
        raise
    except TimeoutError as exc:
        raise SystemExit(
            f"GitHub API {method} {api_path} timed out after {GITHUB_API_TIMEOUT_S}s."
        ) from exc
    except error.URLError as exc:
        raise SystemExit(
            f"GitHub API {method} {api_path} failed: {exc.reason}"
        ) from exc
    if not payload:
        return None
    return json.loads(payload)


def _list_releases(repo: str) -> list[dict[str, object]]:
    releases: list[dict[str, object]] = []
    page = 1
    while True:
        payload = _github_request("GET", repo, f"releases?per_page=100&page={page}")
        if not isinstance(payload, list):
            raise SystemExit("Unexpected GitHub releases payload shape.")
        if not payload:
            break
        releases.extend(payload)
        if len(payload) < 100:
            break
        page += 1
    return releases


def cleanup_superseded_releases(
    repo: str,
    *,
    current_tag: str,
    release_title_prefix: str,
) -> list[ReleaseSummary]:
    removed = select_superseded_releases(
        _list_releases(repo),
        current_tag=current_tag,
        release_title_prefix=release_title_prefix,
    )
    for release in removed:
        print(f"Deleting superseded Wheel / ESP release {release.tag}", flush=True)
        _github_request("DELETE", repo, f"releases/{release.id}")
        try:
            _github_request("DELETE", repo, f"git/refs/tags/{release.tag}")
        except error.HTTPError as exc:
            if exc.code != 404:
                raise
            print(f"Tag {release.tag} was already absent", flush=True)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extracted helper commands for the main-release workflow."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compute_parser = subparsers.add_parser("compute-version")
    compute_parser.add_argument("--repo-root", default=None)
    compute_parser.add_argument("--github-output", default=None)

    wheel_parser = subparsers.add_parser("build-wheel")
    wheel_parser.add_argument("--repo-root", default=None)
    wheel_parser.add_argument("--version", required=True)

    wheelhouse_parser = subparsers.add_parser("build-wheelhouse")
    wheelhouse_parser.add_argument("--wheel-path", required=True)
    wheelhouse_parser.add_argument("--version", required=True)
    wheelhouse_parser.add_argument("--output-dir", required=True)
    wheelhouse_parser.add_argument(
        "--machine", required=True, choices=sorted(PI_WHEEL_TARGETS)
    )

    manifest_parser = subparsers.add_parser("generate-firmware-manifest")
    manifest_parser.add_argument("--firmware-dir", required=True)
    manifest_parser.add_argument("--generated-from", default=None)

    cleanup_parser = subparsers.add_parser("cleanup-releases")
    cleanup_parser.add_argument("--repo", required=True)
    cleanup_parser.add_argument("--current-tag", required=True)
    cleanup_parser.add_argument(
        "--release-title-prefix",
        default="Wheel / ESP release",
    )
    cleanup_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "compute-version":
        version_info = compute_release_version_info(_repo_root(args.repo_root))
        if args.github_output:
            write_github_output(Path(args.github_output), version_info)
        else:
            print(json.dumps(asdict(version_info), indent=2))
        return 0

    if args.command == "build-wheel":
        wheel_path = build_server_wheel(_repo_root(args.repo_root), args.version)
        print(wheel_path, flush=True)
        return 0

    if args.command == "build-wheelhouse":
        output = Path(args.output_dir) / wheelhouse_name(args.version, args.machine)
        print(build_wheelhouse(Path(args.wheel_path), output, args.machine), flush=True)
        return 0

    if args.command == "generate-firmware-manifest":
        manifest_path = write_firmware_manifest(
            Path(args.firmware_dir).resolve(),
            generated_from=args.generated_from,
        )
        print(manifest_path, flush=True)
        return 0

    selected = select_superseded_releases(
        _list_releases(args.repo),
        current_tag=args.current_tag,
        release_title_prefix=args.release_title_prefix,
    )
    if args.dry_run:
        print(json.dumps([asdict(release) for release in selected], indent=2))
        return 0
    cleanup_superseded_releases(
        args.repo,
        current_tag=args.current_tag,
        release_title_prefix=args.release_title_prefix,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
