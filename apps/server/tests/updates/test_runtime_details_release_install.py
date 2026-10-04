"""Update status names the build on a release install (no .git, no UI sources)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from vibesensor.updates.status.runtime_details import (
    UI_BUILD_METADATA_FILE,
    collect_runtime_details,
    hash_tree,
)

_COMMIT = "3ff28406d8ab9e956ab210f581d0b45e4f62f82c"


def _release_install(tmp_path: Path) -> tuple[Path, Path]:
    """/opt/VibeSensor without apps/ui or static, and the wheel's packaged static."""
    repo = tmp_path / "opt" / "VibeSensor"
    (repo / "apps" / "server").mkdir(parents=True)
    static = tmp_path / "site-packages" / "vibesensor" / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>ok</html>\n", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log('ui')\n", encoding="utf-8")
    record = {
        "ui_source_hash": "source-hash-from-build",
        "static_assets_hash": hash_tree(static, ignore_names={UI_BUILD_METADATA_FILE}),
        "git_commit": _COMMIT,
    }
    (static / UI_BUILD_METADATA_FILE).write_text(json.dumps(record), encoding="utf-8")
    return repo, static


def test_a_release_install_reports_its_stamped_commit_and_packaged_build(tmp_path: Path) -> None:
    repo, static = _release_install(tmp_path)

    with patch("vibesensor._version.__commit__", _COMMIT):
        details = collect_runtime_details(repo, packaged_static=static)

    assert details.commit == _COMMIT
    assert details.static_build_commit == _COMMIT
    assert details.ui_source_hash == details.static_build_source_hash == "source-hash-from-build"
    assert details.static_assets_hash
    assert details.has_packaged_static is True
    assert details.assets_verified is True


def test_a_changed_packaged_asset_is_not_verified(tmp_path: Path) -> None:
    repo, static = _release_install(tmp_path)
    (static / "assets" / "app.js").write_text("tampered\n", encoding="utf-8")

    details = collect_runtime_details(repo, packaged_static=static)

    assert details.assets_verified is False


def test_a_wheel_without_its_build_record_is_not_verified(tmp_path: Path) -> None:
    repo, static = _release_install(tmp_path)
    (static / UI_BUILD_METADATA_FILE).unlink()

    with patch("vibesensor._version.__commit__", ""):
        details = collect_runtime_details(repo, packaged_static=static)

    assert (details.commit, details.static_build_commit, details.ui_source_hash) == ("", "", "")
    assert details.has_packaged_static is True
    assert details.assets_verified is False
