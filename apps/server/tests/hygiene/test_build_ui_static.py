"""Guard build_ui_static.py through CLI-visible artifacts and process boundaries."""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._paths import REPO_ROOT

_BUILD_UI_STATIC = REPO_ROOT / "tools" / "build_ui_static.py"
_UI_BOOTSTRAP_HELPER = REPO_ROOT / "tools" / "ui" / "ensure_ui_bootstrap.mjs"


def _load_temp_build_ui_static(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    script_path = repo / "tools" / "build_ui_static.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_BUILD_UI_STATIC.read_text(encoding="utf-8"), encoding="utf-8")
    helper_path = repo / "tools" / "ui" / "ensure_ui_bootstrap.mjs"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text(_UI_BOOTSTRAP_HELPER.read_text(encoding="utf-8"), encoding="utf-8")

    ui_dir = repo / "apps" / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / "node_modules").mkdir()
    package_lock = ui_dir / "package-lock.json"
    package_lock.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    lock_hash = hashlib.sha256(package_lock.read_bytes()).hexdigest()
    (ui_dir / ".npm-ci-lock.sha256").write_text(f"{lock_hash}\n", encoding="utf-8")
    (ui_dir / "dist").mkdir()

    static_dir = repo / "apps" / "server" / "vibesensor" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location("build_ui_static_local", script_path)
    assert spec is not None and spec.loader is not None, f"Unable to load {script_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, repo, ui_dir, static_dir


def _install_fake_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    module,
    ui_dir: Path,
    *,
    git_head: str = "deadbeef",
) -> list[list[str]]:
    commands: list[list[str]] = []
    dist_dir = ui_dir / "dist"

    def _fake_run(
        command: list[str],
        cwd: str | Path | None = None,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check, capture_output, text
        command_list = [str(part) for part in command]
        commands.append(command_list)
        if command_list[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(command_list, 0, stdout=f"{git_head}\n", stderr="")
        if command_list[:2] == ["npm", "run"] and command_list[2] in {
            "build",
            "build:prevalidated-contracts",
        }:
            (dist_dir / "index.html").write_text(
                f"<!doctype html>\n<!-- {command_list[2]} -->\n",
                encoding="utf-8",
            )
            (dist_dir / "bundle.js").write_text("// built\n", encoding="utf-8")
        return subprocess.CompletedProcess(command_list, 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    return commands


def _npm_run_labels(commands: list[list[str]]) -> list[str]:
    return [command[2] for command in commands if command[:2] == ["npm", "run"]]


def test_build_ui_static_builds_and_syncs_static_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, repo, ui_dir, static_dir = _load_temp_build_ui_static(tmp_path)
    commands = _install_fake_subprocess(monkeypatch, module, ui_dir)

    module.main([])

    assert _npm_run_labels(commands) == ["sync:generated-contracts", "typecheck", "build"]
    assert any(
        command[0] == "node" and Path(command[1]).name == "ensure_ui_bootstrap.mjs"
        for command in commands
    )
    assert (static_dir / "index.html").read_text(
        encoding="utf-8"
    ) == "<!doctype html>\n<!-- build -->\n"
    metadata = json.loads((static_dir / module.UI_BUILD_METADATA_FILE).read_text(encoding="utf-8"))
    assert metadata["git_commit"] == "deadbeef"
    assert metadata["ui_source_hash"]
    assert metadata["static_assets_hash"]
    assert (
        capsys.readouterr().out.strip()
        == f"Synced {ui_dir / 'dist'} -> {repo / 'apps' / 'server' / 'vibesensor' / 'static'}"
    )


def test_build_ui_static_still_skips_typecheck_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _repo, ui_dir, static_dir = _load_temp_build_ui_static(tmp_path)
    commands = _install_fake_subprocess(monkeypatch, module, ui_dir)

    module.main(["--skip-typecheck"])

    assert _npm_run_labels(commands) == ["sync:generated-contracts", "build"]
    assert (static_dir / "index.html").read_text(
        encoding="utf-8"
    ) == "<!doctype html>\n<!-- build -->\n"


def test_build_ui_static_passes_skip_npm_ci_to_shared_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _repo, ui_dir, _static_dir = _load_temp_build_ui_static(tmp_path)
    commands = _install_fake_subprocess(monkeypatch, module, ui_dir)

    module.main(["--skip-npm-ci", "--skip-typecheck"])

    bootstrap_command = next(command for command in commands if command[0] == "node")
    assert "--skip-npm-ci" in bootstrap_command


def test_build_ui_static_can_use_prevalidated_contract_build_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _repo, ui_dir, static_dir = _load_temp_build_ui_static(tmp_path)
    commands = _install_fake_subprocess(monkeypatch, module, ui_dir)

    module.main(["--skip-typecheck", "--assume-prevalidated-contracts"])

    assert _npm_run_labels(commands) == ["sync:generated-contracts", "build:prevalidated-contracts"]
    assert (static_dir / "index.html").read_text(encoding="utf-8") == (
        "<!doctype html>\n<!-- build:prevalidated-contracts -->\n"
    )


def test_build_ui_static_rejects_prevalidated_contracts_without_skip_typecheck(
    tmp_path: Path,
) -> None:
    module, _repo, _ui_dir, _static_dir = _load_temp_build_ui_static(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        module.main(["--assume-prevalidated-contracts"])

    assert exc_info.value.code == 2


def test_build_ui_static_stays_importable_without_msgspec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "msgspec":
            raise ModuleNotFoundError(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    module, _repo, _ui_dir, _static_dir = _load_temp_build_ui_static(tmp_path)

    assert module.UI_BUILD_METADATA_FILE == ".vibesensor-ui-build.json"
