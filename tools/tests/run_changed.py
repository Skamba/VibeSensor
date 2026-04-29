#!/usr/bin/env python3
"""Run fast, heuristic checks for files changed in the current branch."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
BACKEND_TESTS_ROOT = PurePosixPath("apps/server/tests")
BACKEND_SOURCE_ROOT = PurePosixPath("apps/server/vibesensor")
DOC_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    ".github/copilot-instructions.md",
}
HYGIENE_TRIGGER_PATHS = {
    "Makefile",
    ".python-version",
    ".nvmrc",
    "docker-compose.yml",
    "docker-compose.dev.yml",
}
HYGIENE_TRIGGER_PREFIXES = (".githooks/", ".github/", "tools/")


@dataclass(frozen=True)
class PlannedCommand:
    label: str
    argv: tuple[str, ...]


def _git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _git_has_ref(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _resolve_base_ref(requested: str | None) -> str:
    candidates = [requested] if requested else ["origin/main", "main"]
    for candidate in candidates:
        if candidate and _git_has_ref(candidate):
            return candidate
    raise SystemExit(
        "No base ref found. Fetch origin/main or rerun with --base-ref <ref> (for example main)."
    )


def _changed_files(base_ref: str) -> tuple[str, ...]:
    try:
        merge_base = _git_output("merge-base", base_ref, "HEAD")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Unable to find a common ancestor between {base_ref} and HEAD. "
            "Fetch the latest history or rerun with --base-ref <ref>."
        ) from exc
    committed = {
        line
        for line in _git_output(
            "diff", "--name-only", f"{merge_base}..HEAD"
        ).splitlines()
        if line.strip()
    }
    staged = {
        line
        for line in _git_output("diff", "--name-only", "--cached").splitlines()
        if line.strip()
    }
    unstaged = {
        line for line in _git_output("diff", "--name-only").splitlines() if line.strip()
    }
    untracked = {
        line
        for line in _git_output(
            "ls-files", "--others", "--exclude-standard"
        ).splitlines()
        if line.strip()
    }
    return tuple(sorted(committed | staged | unstaged | untracked))


def _is_markdown_path(path: str) -> bool:
    return path.endswith(".md") or path in DOC_FILES or path.startswith("docs/")


def _test_target_for_changed_test(path: str) -> str:
    candidate = PurePosixPath(path)
    if (
        candidate.name.startswith("test_")
        and candidate.suffix == ".py"
        and (ROOT / candidate).exists()
    ):
        return candidate.as_posix()
    return candidate.parent.as_posix()


def _mirrored_backend_test_target(path: str) -> str | None:
    source_path = PurePosixPath(path)
    try:
        relative = source_path.relative_to(BACKEND_SOURCE_ROOT)
    except ValueError:
        return None
    if not relative.parts:
        return None
    candidate = BACKEND_TESTS_ROOT / relative.parts[0]
    if (ROOT / candidate).is_dir():
        return candidate.as_posix()
    return None


def _plan_commands(changed_files: tuple[str, ...]) -> tuple[PlannedCommand, ...]:
    docs_changed = False
    ui_changed = False
    ui_unit_test_changed = False
    backend_fallback = False
    pytest_targets: set[str] = set()

    for path in changed_files:
        normalized = PurePosixPath(path).as_posix()
        if _is_markdown_path(normalized):
            docs_changed = True
            continue

        if normalized.startswith("apps/server/tests/"):
            pytest_targets.add(_test_target_for_changed_test(normalized))
            continue

        if normalized.startswith("apps/server/vibesensor/"):
            mirrored_target = _mirrored_backend_test_target(normalized)
            if mirrored_target is not None:
                pytest_targets.add(mirrored_target)
            else:
                backend_fallback = True
            continue

        if normalized.startswith("apps/ui/"):
            ui_changed = True
            if normalized.startswith("apps/ui/src/"):
                ui_unit_test_changed = True
            continue

        if normalized in HYGIENE_TRIGGER_PATHS or normalized.startswith(
            HYGIENE_TRIGGER_PREFIXES
        ):
            pytest_targets.add("apps/server/tests/hygiene")
            continue

        if normalized.startswith("apps/server/"):
            backend_fallback = True

    commands: list[PlannedCommand] = []
    if docs_changed:
        commands.append(PlannedCommand("docs-lint", ("make", "docs-lint")))
    if ui_unit_test_changed:
        commands.append(PlannedCommand("ui-test", ("make", "ui-test")))
    if ui_changed:
        commands.append(PlannedCommand("ui-typecheck", ("make", "ui-typecheck")))
    if backend_fallback:
        commands.append(PlannedCommand("backend-tests", ("make", "test")))
    elif pytest_targets:
        commands.append(
            PlannedCommand(
                "pytest",
                (sys.executable, "-m", "pytest", "-q", *tuple(sorted(pytest_targets))),
            )
        )
    return tuple(commands)


def _run_planned_commands(commands: tuple[PlannedCommand, ...]) -> int:
    for command in commands:
        print(f"[test-changed] {command.label}: {shlex.join(command.argv)}")
        completed = subprocess.run(command.argv, cwd=ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        help="Git ref to diff against (default: origin/main, falling back to main).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected commands without running them.",
    )
    args = parser.parse_args(argv)

    base_ref = _resolve_base_ref(args.base_ref)
    changed_files = _changed_files(base_ref)
    if not changed_files:
        print(f"[test-changed] No changed files detected vs {base_ref}.")
        return 0

    print(f"[test-changed] Changed files vs {base_ref}:")
    for path in changed_files:
        print(f"  - {path}")

    commands = _plan_commands(changed_files)
    if not commands:
        print("[test-changed] No mapped checks for the current diff.")
        return 0

    if args.dry_run:
        for command in commands:
            print(f"[test-changed] {command.label}: {shlex.join(command.argv)}")
        return 0

    return _run_planned_commands(commands)


if __name__ == "__main__":
    raise SystemExit(main())
