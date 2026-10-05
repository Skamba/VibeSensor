"""The firmware build identity follows the firmware build inputs and nothing else."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from tests._paths import REPO_ROOT
from vibesensor.domain.sensor_firmware import firmware_status


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


def _write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, committer_date: str) -> None:
    env = {**os.environ, "GIT_COMMITTER_DATE": committer_date, "GIT_AUTHOR_DATE": committer_date}
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "add", "-A"], check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "change"], check=True, env=env)


def _firmware_checkout(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _write(repo, "firmware/esp/platformio.ini", "[env:m5stack_atom]\n")
    _write(repo, "firmware/esp/src/main.cpp", "void setup() {}\n")
    _write(repo, "firmware/esp/lib/proto/proto.h", "#pragma once\n")
    _write(repo, "firmware/esp/include/contracts.h", "#pragma once\n")
    _write(repo, "apps/server/vibesensor/_version.py", '__version__ = "0.0.0-dev"\n')
    _commit(repo, "2026-10-04T18:03:00+02:00")


def test_a_server_release_that_leaves_the_firmware_alone_keeps_its_identity(
    tmp_path: Path,
) -> None:
    _firmware_checkout(tmp_path)
    before = _build_version.firmware_build_version(tmp_path)
    assert before.startswith("fw-20261004.1603+")  # committer date in UTC

    # The release workflow stamps _version.py with the release and commit before
    # it builds the firmware; docs, tests and server code change between releases.
    _main_release.stamp_version_file(
        tmp_path / "apps" / "server" / "vibesensor" / "_version.py", "2026.10.6.3", "ab" * 20
    )
    _write(tmp_path, "apps/server/vibesensor/app.py", "print('new server')\n")
    _write(tmp_path, "firmware/esp/README.md", "# Firmware\n")
    _write(tmp_path, "firmware/esp/test/test_x/test_main.cpp", "int main() {}\n")
    _commit(tmp_path, "2026-10-06T09:00:00+00:00")

    assert _build_version.firmware_build_version(tmp_path) == before


def test_a_firmware_input_change_changes_the_digest_and_its_commit_the_date(
    tmp_path: Path,
) -> None:
    _firmware_checkout(tmp_path)
    before = _build_version.firmware_build_version(tmp_path)

    for relative in (
        "firmware/esp/platformio.ini",
        "firmware/esp/src/main.cpp",
        "firmware/esp/lib/proto/proto.h",
        "firmware/esp/include/contracts.h",
    ):
        path = tmp_path / relative
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "// changed\n", encoding="utf-8")
        uncommitted = _build_version.firmware_build_version(tmp_path)
        assert uncommitted.split("+")[0] == before.split("+")[0]
        assert uncommitted != before, relative
        path.write_text(original, encoding="utf-8")

    _write(tmp_path, "firmware/esp/src/main.cpp", "void setup() { /* v2 */ }\n")
    _commit(tmp_path, "2026-10-07T10:30:00+00:00")
    after = _build_version.firmware_build_version(tmp_path)

    assert after.startswith("fw-20261007.1030+")
    assert firmware_status(before, after) == "outdated"


def test_a_build_without_git_reports_an_unknown_date(tmp_path: Path) -> None:
    _write(tmp_path, "firmware/esp/src/main.cpp", "void setup() {}\n")

    identity = _build_version.firmware_build_version(tmp_path)

    assert identity == (
        f"fw-00000000.0000+{_build_version.firmware_inputs_digest(tmp_path / 'firmware/esp')}"
    )


def test_this_checkout_stamps_an_identity_the_server_understands() -> None:
    identity = _build_version.firmware_build_version(REPO_ROOT)
    digest = identity.rpartition("+")[2]

    assert len(identity.encode()) <= 32  # the HELLO firmware_version field
    assert firmware_status(f"fw-00000000.0000+{digest}", identity) == "current"
    assert firmware_status("fw-00000000.0000+ffffffffffff", identity) == "outdated"
