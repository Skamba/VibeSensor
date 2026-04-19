"""Guards for the local CI-parallel runner bootstrap behavior."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_CI_PARALLEL = REPO_ROOT / "tools" / "tests" / "run_ci_parallel.py"


def _load_ci_parallel_module():
    spec = importlib.util.spec_from_file_location("ci_parallel_local_for_tests", _CI_PARALLEL)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CI_PARALLEL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bootstrap_uses_shared_ui_bootstrap_helper_when_npm_ci_is_needed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    ui_dir = tmp_path / "apps" / "ui"
    ui_dir.mkdir(parents=True)
    helper_path = tmp_path / "tools" / "ui" / "ensure_ui_bootstrap.mjs"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("// helper\n", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "UI_DIR", ui_dir)
    monkeypatch.setattr(module, "UI_BOOTSTRAP_HELPER", helper_path)

    steps = module._bootstrap_steps("python3", True, include_platformio=False)

    assert steps[-1] == module.Step(
        "ui deps: ensure bootstrap",
        ["node", "../../tools/ui/ensure_ui_bootstrap.mjs"],
        cwd=ui_dir,
    )


def test_main_refuses_skip_bootstrap_when_release_smoke_would_race_ui_jobs(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    module = _load_ci_parallel_module()
    ui_dir = tmp_path / "apps" / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    (ui_dir / "node_modules").mkdir()

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(module, "UI_DIR", ui_dir)
    release_smoke_step = module.Step(
        "Release smoke validation",
        ["python3", "tools/tests/run_release_smoke.py"],
    )
    ui_step = module.Step("UI lint", ["npm", "run", "lint"], cwd=ui_dir)
    monkeypatch.setattr(
        module,
        "_job_steps",
        lambda python_cmd: {
            "frontend-typecheck": [ui_step],
            "ui-smoke": [ui_step],
            "release-smoke": [release_smoke_step],
        },
    )

    def _unexpected_bootstrap(_steps):
        raise AssertionError("bootstrap should not run when the race guard exits early")

    monkeypatch.setattr(module, "_run_bootstrap", _unexpected_bootstrap)
    monkeypatch.setattr(
        module,
        "_ui_bootstrap_status",
        lambda skip_npm_ci: module.UiBootstrapStatus(
            needs_npm_ci=not skip_npm_ci,
            lock_hash="lock",
            current_lock_hash="",
            node_modules_exists=True,
        ),
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "run_ci_parallel.py",
            "--skip-bootstrap",
            "--job",
            "frontend-typecheck",
            "--job",
            "ui-smoke",
            "--job",
            "release-smoke",
        ],
    )

    result = module.main()
    output = capsys.readouterr().out

    assert result == 2
    assert "release-smoke would trigger npm ci inside apps/ui" in output


def test_release_smoke_skip_ui_build_does_not_trigger_ui_race(monkeypatch) -> None:
    module = _load_ci_parallel_module()
    release_smoke_step = module.Step(
        "Release smoke validation",
        ["python3", "tools/tests/run_release_smoke.py", "--skip-ui-build"],
    )
    ui_step = module.Step("UI lint", ["npm", "run", "lint"], cwd=module.UI_DIR)
    jobs = {
        "frontend-typecheck": [ui_step],
        "release-smoke": [release_smoke_step],
    }

    monkeypatch.setattr(
        module,
        "_ui_bootstrap_status",
        lambda skip_npm_ci: module.UiBootstrapStatus(
            needs_npm_ci=not skip_npm_ci,
            lock_hash="lock",
            current_lock_hash="",
            node_modules_exists=True,
        ),
    )

    assert not module._job_runs_release_smoke_ui_build([release_smoke_step])
    assert not module._shared_ui_workspace_would_race(
        ["frontend-typecheck", "release-smoke"],
        jobs,
        skip_bootstrap=True,
        skip_npm_ci=False,
    )


def test_ui_bootstrap_status_reads_shared_helper_json(monkeypatch, tmp_path: Path) -> None:
    module = _load_ci_parallel_module()
    ui_dir = tmp_path / "apps" / "ui"
    ui_dir.mkdir(parents=True)
    helper_path = tmp_path / "tools" / "ui" / "ensure_ui_bootstrap.mjs"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("// helper\n", encoding="utf-8")

    monkeypatch.setattr(module, "UI_DIR", ui_dir)
    monkeypatch.setattr(module, "UI_BOOTSTRAP_HELPER", helper_path)
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, cwd, text: json.dumps(
            {
                "needs_npm_ci": True,
                "lock_hash": "abc",
                "current_lock_hash": "",
                "node_modules_exists": False,
            }
        ),
    )

    status = module._ui_bootstrap_status(False)

    assert status == module.UiBootstrapStatus(
        needs_npm_ci=True,
        lock_hash="abc",
        current_lock_hash="",
        node_modules_exists=False,
    )
