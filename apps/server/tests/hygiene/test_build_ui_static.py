"""Guard the explicit UI contract-sync step in build_ui_static.py."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_BUILD_UI_STATIC = REPO_ROOT / "tools" / "build_ui_static.py"


def _load_temp_build_ui_static(tmp_path: Path):
    repo = tmp_path / "repo"
    script_path = repo / "tools" / "build_ui_static.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_BUILD_UI_STATIC.read_text(encoding="utf-8"), encoding="utf-8")

    ui_dir = repo / "apps" / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "node_modules").mkdir()
    package_lock = ui_dir / "package-lock.json"
    package_lock.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    lock_hash = hashlib.sha256(package_lock.read_bytes()).hexdigest()
    (ui_dir / ".npm-ci-lock.sha256").write_text(f"{lock_hash}\n", encoding="utf-8")
    (ui_dir / "dist").mkdir()
    (ui_dir / "dist" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")

    (repo / "apps" / "server" / "vibesensor" / "static").mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location("build_ui_static_local", script_path)
    assert spec is not None and spec.loader is not None, f"Unable to load {script_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, repo, ui_dir


def test_build_ui_static_syncs_generated_contracts_before_typecheck_and_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module, _, ui_dir = _load_temp_build_ui_static(tmp_path)
    commands: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(
        module,
        "_run",
        lambda command, cwd: commands.append((command, cwd)),
    )

    module.main([])

    assert commands == [
        (["npm", "run", "sync:generated-contracts"], ui_dir),
        (["npm", "run", "typecheck"], ui_dir),
        (["npm", "run", "build"], ui_dir),
    ]


def test_build_ui_static_still_syncs_when_typecheck_is_skipped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module, _, ui_dir = _load_temp_build_ui_static(tmp_path)
    commands: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(
        module,
        "_run",
        lambda command, cwd: commands.append((command, cwd)),
    )

    module.main(["--skip-typecheck"])

    assert commands == [
        (["npm", "run", "sync:generated-contracts"], ui_dir),
        (["npm", "run", "build"], ui_dir),
    ]
