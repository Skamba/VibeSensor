from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


def _load_release_smoke_runner():
    repo_root = Path(__file__).resolve().parents[5]
    script_path = repo_root / "tools" / "tests" / "run_release_smoke.py"
    spec = importlib.util.spec_from_file_location("run_release_smoke", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, repo_root


def _set_repo_root(module: object, repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_script = repo_root / "tools" / "tests" / "run_release_smoke.py"
    fake_script.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "__file__", str(fake_script))


def test_run_release_smoke_main_builds_artifacts_and_runs_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module, _repo_root = _load_release_smoke_runner()
    repo_root = tmp_path / "repo"
    dist_dir = repo_root / "apps" / "server" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    built_wheel = dist_dir / "vibesensor-2025.6.15-py3-none-any.whl"
    commands: list[tuple[list[str], Path, dict[str, str] | None]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: str,
        check: bool,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        commands.append((list(cmd), Path(cwd), env))
        if "-m build --wheel apps/server/" in " ".join(cmd):
            built_wheel.parent.mkdir(parents=True, exist_ok=True)
            built_wheel.write_text("wheel", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    _set_repo_root(module, repo_root, monkeypatch)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.venv.EnvBuilder, "create", lambda self, path: None)

    exit_code = module.main(["--skip-npm-ci", "--port", "18081"])

    command_lines = [" ".join(cmd) for cmd, _cwd, _env in commands]
    assert exit_code == 0
    assert built_wheel.is_file()
    assert any("tools/build_ui_static.py" in line for line in command_lines)
    assert any("-m build --wheel apps/server/" in line for line in command_lines)
    assert any("-m pip install" in line and str(built_wheel) in line for line in command_lines)
    assert any("smoke-server" in line and "--port 18081" in line for line in command_lines)


def test_run_release_smoke_main_reuses_existing_wheel_and_skips_ui_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module, _repo_root = _load_release_smoke_runner()
    repo_root = tmp_path / "repo"
    dist_dir = repo_root / "apps" / "server" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    commands: list[tuple[list[str], Path, dict[str, str] | None]] = []
    existing_wheel = dist_dir / "prebuilt.whl"
    existing_wheel.write_text("wheel", encoding="utf-8")

    def fake_run(
        cmd: list[str],
        *,
        cwd: str,
        check: bool,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        commands.append((list(cmd), Path(cwd), env))
        return subprocess.CompletedProcess(cmd, 0)

    _set_repo_root(module, repo_root, monkeypatch)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.venv.EnvBuilder, "create", lambda self, path: None)

    exit_code = module.main(["--skip-ui-build", "--wheel-path", "apps/server/dist/prebuilt.whl"])

    command_lines = [" ".join(cmd) for cmd, _cwd, _env in commands]
    assert exit_code == 0
    assert not any("tools/build_ui_static.py" in line for line in command_lines)
    assert not any("-m build --wheel apps/server/" in line for line in command_lines)
    assert any(
        "-m pip install" in line and str(existing_wheel.resolve()) in line for line in command_lines
    )


def test_run_release_smoke_main_rejects_missing_wheel_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module, _repo_root = _load_release_smoke_runner()
    repo_root = tmp_path / "repo"
    _set_repo_root(module, repo_root, monkeypatch)

    with pytest.raises(RuntimeError, match="Wheel path does not exist or is not a .whl file"):
        module.main(["--skip-ui-build", "--wheel-path", "apps/server/dist/missing.whl"])
