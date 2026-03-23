"""Guards for the local CI-parallel runner bootstrap behavior."""

from __future__ import annotations

import hashlib
import importlib.util
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


def test_bootstrap_marks_ui_lock_hash_after_shared_npm_ci(monkeypatch, tmp_path: Path) -> None:
    module = _load_ci_parallel_module()
    ui_dir = tmp_path / "apps" / "ui"
    ui_dir.mkdir(parents=True)
    package_lock = ui_dir / "package-lock.json"
    package_lock.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LOG_DIR", tmp_path / "logs")
    module.LOG_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "UI_DIR", ui_dir)
    monkeypatch.setattr(module, "UI_NODE_MODULES", ui_dir / "node_modules")
    monkeypatch.setattr(module, "UI_LOCK_FILE", package_lock)
    monkeypatch.setattr(module, "UI_LOCK_HASH_FILE", ui_dir / ".npm-ci-lock.sha256")
    monkeypatch.setattr(module, "_run_step", lambda step, log_file: 0)

    result = module._run_bootstrap(
        module._bootstrap_steps("python3", True, include_platformio=False)
    )

    assert result == 0
    assert (
        module.UI_LOCK_HASH_FILE.read_text(encoding="utf-8").strip()
        == hashlib.sha256(package_lock.read_bytes()).hexdigest()
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
    monkeypatch.setattr(module, "UI_NODE_MODULES", ui_dir / "node_modules")
    monkeypatch.setattr(module, "UI_LOCK_FILE", ui_dir / "package-lock.json")
    monkeypatch.setattr(module, "UI_LOCK_HASH_FILE", ui_dir / ".npm-ci-lock.sha256")
    monkeypatch.setattr(
        module,
        "_job_steps",
        lambda python_cmd: {
            "frontend-typecheck": [],
            "ui-smoke": [],
            "release-smoke": [],
        },
    )

    def _unexpected_bootstrap(_steps):
        raise AssertionError("bootstrap should not run when the race guard exits early")

    monkeypatch.setattr(module, "_run_bootstrap", _unexpected_bootstrap)
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
