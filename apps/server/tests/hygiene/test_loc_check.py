"""Guard loc_check git and non-git file discovery."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests._paths import REPO_ROOT

_LOC_CHECK = REPO_ROOT / "tools" / "dev" / "loc_check.py"


def _load_loc_check_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("loc_check_test_module", _LOC_CHECK)
    assert spec is not None and spec.loader is not None, f"Unable to load {_LOC_CHECK}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tracked_files_prefers_git_listing(monkeypatch) -> None:
    module = _load_loc_check_module()
    repo_root = Path("/tmp/nonexistent")

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert args == (
            [
                "git",
                "-C",
                str(repo_root),
                "ls-files",
                "--cached",
            ],
        )
        assert kwargs["check"] is True
        assert kwargs["text"] is True
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout="apps/server/main.py\nREADME.md\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    assert module._tracked_files(repo_root) == ["apps/server/main.py", "README.md"]


def test_main_falls_back_to_repo_walk_outside_git_checkout(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_loc_check_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "dev").mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (repo_root / "scripts").mkdir()
    (repo_root / "scripts" / "helper.sh").write_text("echo hi\n", encoding="utf-8")
    (repo_root / "node_modules" / "pkg").mkdir(parents=True)
    (repo_root / "node_modules" / "pkg" / "index.js").write_text(
        "console.log('ignore')\n", encoding="utf-8"
    )
    (repo_root / "artifacts").mkdir()
    (repo_root / "artifacts" / "generated.py").write_text("print('ignore')\n", encoding="utf-8")

    monkeypatch.setattr(module, "__file__", str(repo_root / "tools" / "dev" / "loc_check.py"))

    def _raise_git_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, args[0])

    monkeypatch.setattr(module.subprocess, "run", _raise_git_failure)

    assert module.main() == 0

    stdout = capsys.readouterr().out
    assert "src/main.py" in stdout
    assert "scripts/helper.sh" in stdout
    assert "node_modules/pkg/index.js" not in stdout
    assert "artifacts/generated.py" not in stdout


def test_main_fails_when_optional_loc_threshold_is_exceeded(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_loc_check_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "dev").mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text(
        "print('one')\nprint('two')\nprint('three')\n",
        encoding="utf-8",
    )
    (repo_root / "scripts").mkdir()
    (repo_root / "scripts" / "helper.sh").write_text("echo hi\n", encoding="utf-8")

    monkeypatch.setattr(module, "__file__", str(repo_root / "tools" / "dev" / "loc_check.py"))

    def _raise_git_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, args[0])

    monkeypatch.setattr(module.subprocess, "run", _raise_git_failure)

    assert module.main(["--fail-over", "2"]) == 1

    stdout = capsys.readouterr().out
    assert "FAIL: 1 source file(s) exceed 2 lines:" in stdout
    assert "src/main.py" in stdout
    assert "scripts/helper.sh" not in stdout.split("FAIL:", 1)[1]


def test_main_passes_when_optional_loc_threshold_is_not_exceeded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_loc_check_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "dev").mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text(
        "print('one')\nprint('two')\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(repo_root / "tools" / "dev" / "loc_check.py"))

    def _raise_git_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, args[0])

    monkeypatch.setattr(module.subprocess, "run", _raise_git_failure)

    assert module.main(["--fail-over", "2"]) == 0
