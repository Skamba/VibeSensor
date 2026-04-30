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

    assert module.main([]) == 0

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
    assert "FAIL: 1 maintainability size issue(s):" in stdout
    assert "file exceeds threshold and is not allowlisted" in stdout
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


def test_main_fails_for_unallowlisted_large_python_function(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_loc_check_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "dev").mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text(
        "def too_large():\n    one = 1\n    two = 2\n    return one + two\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(repo_root / "tools" / "dev" / "loc_check.py"))

    def _raise_git_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, args[0])

    monkeypatch.setattr(module.subprocess, "run", _raise_git_failure)

    assert module.main(["--file-fail-over", "100", "--function-fail-over", "2"]) == 1

    stdout = capsys.readouterr().out
    assert "function exceeds threshold and is not allowlisted" in stdout
    assert "src/main.py::too_large" in stdout


def test_main_allows_reviewed_file_and_function_allowlist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_loc_check_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "dev").mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text(
        "def reviewed_large_function():\n    one = 1\n    two = 2\n    return one + two\n",
        encoding="utf-8",
    )
    (repo_root / "tools" / "dev" / "maintainability_allowlist.yml").write_text(
        "file_threshold_lines: 2\n"
        "function_threshold_lines: 2\n"
        "files:\n"
        "  src/main.py:\n"
        "    max_lines: 4\n"
        "    reason: Existing large fixture kept for test coverage.\n"
        "functions:\n"
        "  src/main.py::reviewed_large_function:\n"
        "    max_lines: 4\n"
        "    reason: Existing large function kept for test coverage.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(repo_root / "tools" / "dev" / "loc_check.py"))

    def _raise_git_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, args[0])

    monkeypatch.setattr(module.subprocess, "run", _raise_git_failure)

    assert module.main([]) == 0


def test_main_fails_when_allowlisted_file_or_function_grows(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_loc_check_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "dev").mkdir(parents=True)
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text(
        "def reviewed_large_function():\n    one = 1\n    two = 2\n    return one + two\n",
        encoding="utf-8",
    )
    (repo_root / "tools" / "dev" / "maintainability_allowlist.yml").write_text(
        "file_threshold_lines: 2\n"
        "function_threshold_lines: 2\n"
        "files:\n"
        "  src/main.py:\n"
        "    max_lines: 3\n"
        "    reason: Existing large fixture kept for test coverage.\n"
        "functions:\n"
        "  src/main.py::reviewed_large_function:\n"
        "    max_lines: 3\n"
        "    reason: Existing large function kept for test coverage.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "__file__", str(repo_root / "tools" / "dev" / "loc_check.py"))

    def _raise_git_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, args[0])

    monkeypatch.setattr(module.subprocess, "run", _raise_git_failure)

    assert module.main([]) == 1

    stdout = capsys.readouterr().out
    assert "allowlisted file grew past max_lines" in stdout
    assert "allowlisted function grew past max_lines" in stdout
