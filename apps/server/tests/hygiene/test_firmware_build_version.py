"""The firmware build version follows the release stamp, else the checkout."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from tests._paths import REPO_ROOT


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_build_version = _load(
    "firmware_build_version_for_tests",
    REPO_ROOT / "tools" / "firmware" / "firmware_build_version.py",
)
_main_release = _load(
    "main_release_for_firmware_version_tests", REPO_ROOT / "tools" / "release" / "main_release.py"
)


def _version_file(repo_root: Path) -> Path:
    path = repo_root / "apps" / "server" / "vibesensor" / "_version.py"
    path.parent.mkdir(parents=True)
    return path


def test_release_build_reports_the_stamped_release_and_commit(tmp_path: Path) -> None:
    # The release workflow stamps _version.py (build-wheel) before it builds the firmware.
    _main_release.stamp_version_file(_version_file(tmp_path), "2026.10.4.12", "ab" * 20)

    assert _build_version.firmware_build_version(tmp_path) == "2026.10.4.12+abababababab"


def test_local_build_reports_a_dev_version_with_the_checkout_commit(tmp_path: Path) -> None:
    _version_file(tmp_path).write_text(
        (REPO_ROOT / "apps" / "server" / "vibesensor" / "_version.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    commit = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    assert _build_version.firmware_build_version(tmp_path) == f"0.0.0-dev+{commit[:12]}"


def test_version_that_does_not_fit_the_hello_field_fails_the_build(tmp_path: Path) -> None:
    _main_release.stamp_version_file(_version_file(tmp_path), "2026.10.4.12345678901", "ab" * 20)

    with pytest.raises(SystemExit, match="32-byte HELLO field"):
        _build_version.firmware_build_version(tmp_path)
