from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_release_smoke_runner():
    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "tests" / "run_release_smoke.py"
    spec = importlib.util.spec_from_file_location("run_release_smoke", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, repo_root


def test_run_release_smoke_builds_ui_and_wheel_then_runs_smoke(monkeypatch, tmp_path: Path) -> None:
    module, repo_root = _load_release_smoke_runner()
    commands: list[tuple[list[str], Path, dict[str, str] | None]] = []
    built_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
    built_wheel.write_text("wheel", encoding="utf-8")

    monkeypatch.setattr(module, "_build_server_wheel", lambda root: built_wheel)
    monkeypatch.setattr(
        module,
        "_run",
        lambda cmd, *, cwd, env=None: commands.append((list(cmd), cwd, env)),
    )
    monkeypatch.setattr(module.venv.EnvBuilder, "create", lambda self, path: None)
    monkeypatch.setattr(module, "_venv_python", lambda path: path / "bin" / "python")

    exit_code = module.main(["--skip-npm-ci"])

    assert exit_code == 0
    assert commands[0][0] == [module.sys.executable, "tools/build_ui_static.py", "--skip-npm-ci"]
    assert commands[0][1] == repo_root
    assert any(command[0][-1] == str(built_wheel) for command in commands)
    smoke_command = commands[-1]
    assert smoke_command[0][1:4] == ["-m", "vibesensor.release_validation", "smoke-server"]
    assert smoke_command[2] == {
        "VIBESENSOR_CONTRACTS_DIR": str((repo_root / "libs/shared/contracts").resolve()),
    }


def test_run_release_smoke_can_reuse_existing_wheel_and_skip_ui_build(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module, repo_root = _load_release_smoke_runner()
    commands: list[tuple[list[str], Path, dict[str, str] | None]] = []
    existing_wheel = repo_root / "apps" / "server" / "dist" / "prebuilt.whl"
    existing_wheel.parent.mkdir(parents=True, exist_ok=True)
    existing_wheel.write_text("wheel", encoding="utf-8")

    def _unexpected_build(root: Path) -> Path:
        raise AssertionError("wheel build should be skipped when --wheel-path is provided")

    monkeypatch.setattr(module, "_build_server_wheel", _unexpected_build)
    monkeypatch.setattr(
        module,
        "_run",
        lambda cmd, *, cwd, env=None: commands.append((list(cmd), cwd, env)),
    )
    monkeypatch.setattr(module.venv.EnvBuilder, "create", lambda self, path: None)
    monkeypatch.setattr(module, "_venv_python", lambda path: path / "bin" / "python")

    exit_code = module.main(["--skip-ui-build", "--wheel-path", "apps/server/dist/prebuilt.whl"])

    assert exit_code == 0
    assert all(command[0][1] != "tools/build_ui_static.py" for command in commands)
    pip_install_command = next(
        command for command in commands if command[0][-1] == str(existing_wheel.resolve())
    )
    assert pip_install_command[0][-1] == str(existing_wheel.resolve())
