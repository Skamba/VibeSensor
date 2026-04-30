"""Guard ShellCheck target discovery against stale manually curated lists."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests._paths import REPO_ROOT

_MAKEFILE = REPO_ROOT / "Makefile"
_SHELLCHECK_TARGETS = REPO_ROOT / "tools" / "dev" / "shellcheck_targets.py"
_SHELL_SUFFIXES = (".sh", ".sh.template")
_SHELL_SHEBANG_RE = re.compile(r"^#!.*\b(?:ba|da|k|z)?sh\b")


def _load_shellcheck_targets_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "shellcheck_targets_local_test", _SHELLCHECK_TARGETS
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_SHELLCHECK_TARGETS}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_lines(*args: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return tuple(line for line in result.stdout.splitlines() if line.strip())


def _tracked_executable_files() -> set[str]:
    executable: set[str] = set()
    for line in _git_lines("ls-files", "--stage"):
        metadata, _, path = line.partition("\t")
        mode = metadata.split(maxsplit=1)[0]
        if mode == "100755":
            executable.add(path)
    return executable


def _has_shell_shebang(path: Path) -> bool:
    try:
        first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError):
        return False
    return _SHELL_SHEBANG_RE.search(first_line) is not None


def _expected_shellcheck_targets(allowlist: set[str]) -> tuple[str, ...]:
    executable = _tracked_executable_files()
    targets: list[str] = []
    for rel_path in _git_lines("ls-files"):
        if rel_path in allowlist:
            continue
        path = REPO_ROOT / rel_path
        if not path.is_file():
            continue
        if (
            rel_path.startswith(".githooks/")
            or rel_path.endswith(_SHELL_SUFFIXES)
            or (rel_path in executable and _has_shell_shebang(path))
        ):
            targets.append(rel_path)
    return tuple(sorted(targets))


def test_shellcheck_targets_are_discovered_from_tracked_files() -> None:
    module = _load_shellcheck_targets_module()
    allowlist = set(module.SHELLCHECK_ALLOWLIST)

    assert all(reason.strip() for reason in module.SHELLCHECK_ALLOWLIST.values())
    assert tuple(module.shellcheck_targets()) == _expected_shellcheck_targets(allowlist)


def test_make_shell_lint_uses_dynamic_target_discovery() -> None:
    makefile = _MAKEFILE.read_text(encoding="utf-8")

    assert "SHELLCHECK_TARGETS :=" not in makefile
    assert '"$$PYTHON" tools/dev/shellcheck_targets.py' in makefile
    assert "shellcheck --severity=warning -x -s bash" in makefile
